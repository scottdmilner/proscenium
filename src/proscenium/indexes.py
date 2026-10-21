"""The bindings' in-memory state, and the runtime indexes into it (lifecycle.md#undo-and-runtime-state).

This state is a disposable write-through cache of the bindings' records: each binding's scene and
decoded configuration, and, read when first needed, its decoded manifest, with every datablock's
claims and each binding's resources by identity. It holds every candidate of an identity (source-
access.md#copied-bindings), so ownership counts a copy's manifest as ownership.claims does; a lookup
by identity uses the first candidate found, until copied-binding detection decides which is
canonical. The extension's writes go through it, updating memory and writing the records at once,
since the records are what's saved and what undo steps capture. So nothing is read back from the
records after the extension's own writes.

The records change behind the state only when Blender changes data: a file load, undo, or redo.
The extension's handlers for those drop the state, before and after, and the next use rebuilds it
from the records; dropping it before means another extension's handler that runs ahead of these
reads the new data. That's why the state needs the extension registered: without the handlers, a
binding that redo brings back would never be found. Scenes added or removed, as a scene copy, a new
scene, or an append makes them, no handler announces: every use compares the scenes' session_uids
with those the state was built from, and rebuilds if they differ.

The state holds datablock references, which Blender invalidates under it: undo re-reads every
datablock the undone step changed, which a synchronization's managed content always is, and a file
load frees every one. Those come with a rebuild. The user may also remove managed content at any
time, which no handler announces, so every hit is checked before it's returned (a removed ID's
reference raises when touched) and a failed check rebuilds. A manifest is checked whole when it's
returned, since its entries name datablocks: a removed one's entry is reread from the record, where
Blender has cleared it. Claims are keyed by each datablock's session_uid, which no other datablock
in the session gets and an undo re-read keeps, not by its reference: a new datablock often takes a
removed one's address. Only ID references are held, never the structs inside a datablock
(modifiers, mesh elements, nodes): Blender invalidates a removed ID's Python reference but not
those, and one held across undo silently reads freed memory.

Other content brought in by append or link, and a destination collection duplicated on its own,
aren't seen until the next load, undo, or redo; copied-binding detection scans the file itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy

from . import bindings, ownership, records
from .core.source_access import SourceKind
from .records import Loaded, Refused

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from .bindings import BindingConfig
    from .ownership import Claim, Manifest

_tracking = False  # whether the extension's handlers are registered, so the state is kept current
_state: _State | None = None
_rebuilds = 0  # how many times the state was dropped or rebuilt; see rebuilds()


class NotTracking(RuntimeError):  # noqa: N818 (a precondition, raised like RuntimeError)
    """The bindings' state was used without the extension registered, whose handlers keep it current."""


class _Unread:
    """A manifest not read yet."""


_UNREAD = _Unread()


@dataclass(slots=True)
class _Binding:
    """One candidate of a binding identity: a scene's configuration record for it."""

    scene: bpy.types.Scene
    scene_uid: int  # compared instead of the reference: a new scene can take a removed one's address
    config: BindingConfig | Refused
    manifest: Loaded[Manifest] | Refused | None | _Unread = _UNREAD


@dataclass(slots=True)
class _Share:
    """What one destination's manifest adds to the ownership index, so a publication can replace it alone."""

    claimant: str  # the binding its claims name: the first found whose configuration names the destination
    claims: dict[int, Claim]  # by datablock session_uid; a manifest names a datablock at most once
    resources: list[tuple[str, str]]  # the keys it supplies in _Ownership.resources


@dataclass(slots=True)
class _Ownership:
    """Every candidate's manifest, indexed: ownership.claims_from's result, kept per destination."""

    claims: dict[int, list[Claim]]  # by datablock session_uid
    resources: dict[tuple[str, str], bpy.types.ID]  # (binding, resource identity) -> datablock
    unreadable: dict[int, Refused]  # by destination session_uid: manifests that can't be read
    shares: dict[int, _Share]  # by destination session_uid


@dataclass(slots=True)
class _State:
    scenes: tuple[int, ...]  # the session_uids of the scenes it was built from, in order
    bindings: dict[str, list[_Binding]]  # by binding identifier: its candidates, in the order found
    ownership: _Ownership | None = None  # built when first asked for


def start() -> None:
    """The extension registered its handlers: the state can be used."""
    global _tracking
    _tracking = True
    invalidate()


def stop() -> None:
    global _tracking
    _tracking = False
    invalidate()


def invalidate() -> None:
    """Drop the state, after a file load, undo, or redo: the next use rebuilds it from the records."""
    global _state, _rebuilds
    _state = None
    _rebuilds += 1


def rebuilds() -> int:
    """A count that changes whenever the state is dropped or rebuilt from the records, as after a load,
    undo, or redo, or when scenes are added or removed: what keeps runtime state keyed by binding
    identity, such as the synchronization's sources, knows to compare its bindings with binding_ids()."""
    return _rebuilds


# Bindings.


def binding_ids(scene: bpy.types.Scene | None = None) -> list[str]:
    """The bindings, or those with a candidate on scene, in the order they were found or made.

    Every candidate is checked, as a lookup checks the one it returns.
    """
    return _ask(lambda state: _listed(state, scene))


def binding_scene(binding_id: str) -> bpy.types.Scene | None:
    """The scene holding a binding's configuration, or None if no binding has this identifier."""
    found = _ask(lambda state: _first(state, binding_id))
    return None if found is None else found.scene


def config(binding_id: str) -> BindingConfig | Refused | None:
    """A binding's configuration, why it can't be read, or None if no binding has this identifier."""
    found = _ask(lambda state: _first(state, binding_id))
    return None if found is None else found.config


def attached_with_key(key: str) -> Iterator[tuple[str, BindingConfig]]:
    """The bindings whose configuration can be read and is an attached source with this exact key."""
    for binding_id in binding_ids():
        found = config(binding_id)
        if found is not None and not isinstance(found, Refused):
            if found.source is SourceKind.ATTACHED and found.key == key:
                yield binding_id, found


def create(scene: bpy.types.Scene, config: BindingConfig, name: str) -> str:
    """Make a binding with bindings.create, and record it; it has no manifest yet. Returns its identifier.

    Raises NotTracking before changing anything, and what bindings.create raises.
    """
    state = _current()
    binding_id, config = bindings.create(scene, config, name)
    state.bindings[binding_id] = [_Binding(scene, scene.session_uid, config, None)]
    return binding_id


def set_config(binding_id: str, config: BindingConfig) -> None:
    """Store a binding's changed configuration.

    Raises RecordRefused, changing nothing, over one that can't be read; KeyError if there's no such binding.
    """
    found = _existing(binding_id)
    bindings.update(found.scene, binding_id, config)
    if isinstance(found.config, Refused) or found.config.destination != config.destination:
        found.manifest = _UNREAD
        _forget_ownership()  # a destination changes only in repair: rebuilt whole
    found.config = config


# Manifests and ownership.


def manifest(binding_id: str) -> Loaded[Manifest] | Refused | None:
    """A binding's manifest, read through its configuration's destination when first asked for.

    Refused if the configuration or the manifest can't be read; None if the binding has no
    destination (it was removed) or no manifest yet. Raises KeyError if no binding has this identifier.
    """
    return _checked_manifest(_existing(binding_id))


def set_manifest(binding_id: str, manifest: Manifest) -> None:
    """Store a binding's manifest on its destination, replacing only that destination's share of ownership.

    Raises RecordRefused, changing nothing, over one that can't be read; KeyError if there's no such
    binding; ValueError if it has no destination.
    """
    found = _existing(binding_id)
    if isinstance(found.config, Refused) or found.config.destination is None:
        raise ValueError(f"binding {binding_id} has no destination to hold a manifest")
    destination = found.config.destination
    ownership.write_manifest(destination, manifest)
    state = _current()
    loaded = Loaded(manifest, ownership.MANIFEST.version)
    for candidates in state.bindings.values():  # every configuration naming the destination, as a linked copy's does
        for b in candidates:
            if not isinstance(b.config, Refused) and b.config.destination == destination:
                b.manifest = loaded
    if (index := state.ownership) is not None:
        uid = destination.session_uid
        share = index.shares.get(uid)
        _remove_share(index, uid)
        _add_share(state, index, binding_id if share is None else share.claimant, destination, loaded)


def claims_on(datablock: bpy.types.ID) -> list[Claim]:
    """The claims on datablock; none if it is unmanaged (ownership.claims_from says what they mean)."""
    return _ask(lambda state: _checked_claims(state, datablock))


def resource(binding_id: str, resource_id: str) -> bpy.types.ID | None:
    """The datablock of a binding's resource, as its manifest names it."""
    return _ask(lambda state: _checked_resource(state, binding_id, resource_id))


def unreadable_manifests() -> list[Refused]:
    return _ask(lambda state: list(_ownership(state).unreadable.values()))


# The state. Every lookup is a question _ask puts to it: a check that fails raises _Stale, and _ask
# rebuilds the state and asks once more.


class _Stale(Exception):  # noqa: N818
    """A reference the state holds is gone."""


def _ask[T](question: Callable[[_State], T]) -> T:
    try:
        return question(_current())
    except _Stale:
        invalidate()
        return question(_current())


def _current() -> _State:
    global _state, _rebuilds
    if not _tracking:
        raise NotTracking("the extension isn't registered, so the bindings' state can't be kept current")
    scenes = _scene_uids()
    if _state is None or _state.scenes != scenes:
        _state = _State(scenes, _read_bindings())
        _rebuilds += 1
    return _state


def _scene_uids() -> tuple[int, ...]:
    return tuple(scene.session_uid for scene in bpy.data.scenes)


def _read_bindings() -> dict[str, list[_Binding]]:
    found: dict[str, list[_Binding]] = {}
    for scene, binding_id, result in bindings.all_bindings():
        config = result if isinstance(result, Refused) else result.record
        found.setdefault(binding_id, []).append(_Binding(scene, scene.session_uid, config))
    return found


def _listed(state: _State, scene: bpy.types.Scene | None) -> list[str]:
    if not all(_valid(binding_id, b) for binding_id, candidates in state.bindings.items() for b in candidates):
        raise _Stale
    uid = None if scene is None else scene.session_uid
    return [
        binding_id
        for binding_id, candidates in state.bindings.items()
        if uid is None or any(b.scene_uid == uid for b in candidates)
    ]


def _first(state: _State, binding_id: str) -> _Binding | None:
    """The binding's first candidate, checked (see _valid), or None if no binding has this identifier."""
    candidates = state.bindings.get(binding_id)
    if candidates is None:
        return None
    if not _valid(binding_id, candidates[0]):
        raise _Stale
    return candidates[0]


def _existing(binding_id: str) -> _Binding:
    if (found := _ask(lambda state: _first(state, binding_id))) is None:
        raise KeyError(binding_id)
    return found


def _valid(binding_id: str, binding: _Binding) -> bool:
    """Whether the candidate's scene still exists and holds its configuration, and its destination still
    exists; removing a destination clears the configuration's pointer to it."""
    destination = None if isinstance(binding.config, Refused) else binding.config.destination
    return (
        _alive(binding.scene)
        and records.has(binding.scene, bindings.config_key(binding_id))
        and (destination is None or _alive(destination))
    )


def _manifest_of(binding: _Binding) -> Loaded[Manifest] | Refused | None:
    """The binding's manifest, read through its destination the first time."""
    if isinstance(binding.config, Refused):
        return binding.config
    if isinstance(binding.manifest, _Unread):
        destination = binding.config.destination
        binding.manifest = None if destination is None else ownership.read_manifest(destination)
    return binding.manifest


def _checked_manifest(binding: _Binding) -> Loaded[Manifest] | Refused | None:
    """The binding's manifest, reread if a datablock it names was removed; Blender cleared that entry's pointer."""
    found = _manifest_of(binding)
    if isinstance(found, Loaded) and not all(
        e.datablock is None or _alive(e.datablock) for e in found.record.entries.values()
    ):
        binding.manifest = _UNREAD
        _forget_ownership()
        found = _manifest_of(binding)
    return found


def _forget_ownership() -> None:
    if _state is not None:
        _state.ownership = None


def _ownership(state: _State) -> _Ownership:
    """The ownership index, built from every candidate's manifest if it isn't.

    Each destination counts once, as ownership.claims_from counts it, with the first binding found
    whose configuration names it as the claimant.
    """
    if state.ownership is None:
        index = _Ownership({}, {}, {}, {})
        for binding_id, candidates in state.bindings.items():
            for b in candidates:
                if not isinstance(b.config, Refused) and b.config.destination is not None:
                    destination = b.config.destination
                    if destination.session_uid not in index.shares:
                        _add_share(state, index, binding_id, destination, _checked_manifest(b))
        state.ownership = index
    return state.ownership


def _add_share(
    state: _State,
    index: _Ownership,
    claimant: str,
    destination: bpy.types.Collection,
    manifest: Loaded[Manifest] | Refused | None,
) -> None:
    found, unreadable = ownership.claims_from([(claimant, destination, manifest)])
    uid = destination.session_uid
    share = _Share(claimant, {}, [])
    # A binding's resources are those in the manifest of the candidate its lookups use, the first.
    first = state.bindings[claimant][0].config
    supplies = not isinstance(first, Refused) and first.destination == destination
    for datablock, (claim,) in found.items():
        datablock_uid = datablock.session_uid
        index.claims.setdefault(datablock_uid, []).append(claim)
        share.claims[datablock_uid] = claim
        if supplies:
            key = (claimant, claim.resource_id)
            index.resources[key] = datablock
            share.resources.append(key)
    if unreadable:
        index.unreadable[uid] = unreadable[0]
    index.shares[uid] = share


def _remove_share(index: _Ownership, uid: int) -> None:
    if (share := index.shares.pop(uid, None)) is None:
        return
    for datablock_uid, claim in share.claims.items():
        remaining = [c for c in index.claims[datablock_uid] if c is not claim]
        if remaining:
            index.claims[datablock_uid] = remaining
        else:
            del index.claims[datablock_uid]
    for key in share.resources:
        del index.resources[key]
    index.unreadable.pop(uid, None)


def _checked_claims(state: _State, datablock: bpy.types.ID) -> list[Claim]:
    found = _ownership(state).claims.get(datablock.session_uid, [])
    if not all(_alive(claim.destination) for claim in found):
        raise _Stale
    return list(found)


def _checked_resource(state: _State, binding_id: str, resource_id: str) -> bpy.types.ID | None:
    datablock = _ownership(state).resources.get((binding_id, resource_id))
    if datablock is not None and not _alive(datablock):
        raise _Stale
    return datablock


def _alive(id_: bpy.types.ID) -> bool:
    try:
        id_.name  # noqa: B018 - touching a removed ID's reference raises
    except ReferenceError:
        return False
    return True
