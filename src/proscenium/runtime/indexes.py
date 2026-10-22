"""The bindings' in-memory state, and the runtime indexes into it (lifecycle.md#undo-and-runtime-state).

This state is a disposable write-through cache of the bindings' records: each binding's scene and
decoded configuration, and, read when first needed, its decoded manifest, with every datablock's
claims. It holds every candidate of an identity (source-access.md#copied-bindings), and the
canonical-candidate rule's decision on them (proscenium.runtime.candidates). A lookup by identity uses the
canonical candidate, and raises Disabled for an identity with none. Ownership counts every
candidate's manifest, a tagged collection's that no record names included (ownership.Claim), so
copied content is ambiguous rather than any one binding's. The extension's writes go through it,
updating memory and writing the records at once, since the records are what's saved and what undo
steps capture. So nothing is read back from the records after the extension's own writes.

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
reference raises when touched). A removed datablock costs a reread of the one manifest that names
it, where Blender has cleared its entry, and that destination's share of ownership is replaced; a
removed scene or destination clears pointers in the configurations, so it rebuilds the state. A
manifest is checked whole when it's returned, since its entries name datablocks. Claims are keyed
by each datablock's session_uid, which no other datablock in the session gets and an undo re-read
keeps, not by its reference: a new datablock often takes a removed one's address, and a removed
one's claims, left until its share is next replaced, are never found. Only ID references are held,
never the structs inside a datablock (modifiers, mesh elements, nodes): Blender invalidates a
removed ID's Python reference but not those, and one held across undo silently reads freed memory.

Other content brought in by append or link, and a destination collection duplicated on its own,
add no scene, so they're seen at the next load, undo, or redo, or when find_copies() finds the
collections' tags changed, as a synchronization asks it to first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy

from ..core.copies import Candidate, Decision, Reason
from ..core.source_access import SourceKind
from ..persistence import bindings, ownership, records
from ..persistence.bindings import BindingConfig
from ..persistence.ownership import Claim, Manifest
from ..persistence.records import Loaded, RecordRefused, Refused
from . import candidates

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping

    from ..persistence.ownership import ManifestEntry
    from .candidates import CopiedBinding

_tracking = False  # whether the extension's handlers are registered, so the state is kept current
_state: _State | None = None
_rebuilds = 0  # how many times the state was dropped or rebuilt; see rebuilds()


class NotTracking(RuntimeError):  # noqa: N818 (a precondition, raised like RuntimeError)
    """The bindings' state was used without the extension registered, whose handlers keep it current."""


class Disabled(LookupError):  # noqa: N818 (raised like KeyError, for an identity whose candidates are all disabled)
    """A lookup by a binding identity the canonical-candidate rule can't decide: every candidate is disabled
    pending repair (source-access.md#copied-bindings)."""

    report: CopiedBinding

    def __init__(self, report: CopiedBinding) -> None:
        super().__init__(f"binding {report.binding_id} has copies and no canonical candidate ({report.reason})")
        self.report = report


class _Unread:
    """A manifest not read yet."""


_UNREAD = _Unread()
_UNIQUE = Decision(0, Reason.UNIQUE)


@dataclass(slots=True)
class _Binding:
    """One candidate of a binding identity: a scene's configuration record for it."""

    scene: bpy.types.Scene
    scene_uid: int  # compared instead of the reference: a new scene can take a removed one's address
    config: BindingConfig | Refused
    manifest: Loaded[Manifest] | Refused | None | _Unread = _UNREAD


@dataclass(slots=True)
class _Share:
    """What one destination's manifest adds to the ownership index, so a publication can change it alone."""

    claimant: str  # the binding its claims name: the first found whose configuration names the destination
    claims: dict[int, Claim]  # by datablock session_uid; a manifest names a datablock at most once
    entries: dict[str, int]  # resource identity -> its datablock's session_uid, for the entries naming one


@dataclass(slots=True)
class _Ownership:
    """Every candidate's manifest, indexed: the claims on each datablock (ownership.Claim), kept per destination."""

    # By datablock session_uid: one Claim, or a tuple of them for an ambiguous datablock, which is rare, so
    # the common case costs no list (88 bytes each, a quarter of the index).
    claims: dict[int, Claim | tuple[Claim, ...]]
    unreadable: dict[int, Refused]  # by destination session_uid: manifests that can't be read
    shares: dict[int, _Share]  # by destination session_uid


@dataclass(slots=True)
class _State:
    scenes: tuple[int, ...]  # the session_uids of the scenes it was built from, in order
    bindings: dict[str, list[_Binding]]  # by binding identifier: its candidates, in the order found
    # By destination session_uid: the candidates whose configuration names it, with their identifiers, in the
    # order found, so a write reaches them without going through every binding (_by_destination).
    by_destination: dict[int, list[tuple[str, _Binding]]]
    identities: dict[str, candidates.Identity]  # by binding identifier: its candidates, as the rule reads them
    tagged: frozenset[int]  # the session_uids of the tagged collections it was built from (find_copies)
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
    """The bindings, in the order they were found or made; with scene, those whose canonical candidate is on it,
    or, for a binding with none, those with a candidate on it. Every candidate is checked.
    """
    return _ask(lambda state: _listed(state, scene))


def binding_scene(binding_id: str) -> bpy.types.Scene | None:
    """The scene holding a binding's configuration, or None if no binding has this identifier.

    Every lookup by identity, here and below, raises Disabled for a binding with no canonical candidate.
    """
    found = _ask(lambda state: _canonical(state, binding_id))
    return None if found is None else found.scene


def config(binding_id: str) -> BindingConfig | Refused | None:
    """A binding's configuration, why it can't be read, or None if no binding has this identifier."""
    found = _ask(lambda state: _canonical(state, binding_id))
    return None if found is None else found.config


def configs() -> dict[str, BindingConfig | Refused | CopiedBinding]:
    """Every binding's configuration, why it can't be read, or, for one with no canonical candidate, its
    candidates: one pass over the bindings, checking each one's candidates."""
    return _ask(_configs)


def copied_bindings() -> list[CopiedBinding]:
    """Every binding identity that isn't unique, with its candidates and the rule's decision."""
    return _ask(_copied)


def find_copies() -> None:
    """Rebuild the state if the local collections' destination tags changed since it was built, as duplicating
    a collection on its own changes them, which no handler announces. Checks every collection's records."""
    if _state is not None and bindings.tagged_uids() != _state.tagged:
        invalidate()


def attached_with_key(key: str) -> list[tuple[str, BindingConfig]]:
    """The bindings whose configuration can be read and is an attached source with this exact key; one with copies
    and no canonical candidate isn't one of them."""
    return [
        (binding_id, config)
        for binding_id, config in configs().items()
        if isinstance(config, BindingConfig) and config.source is SourceKind.ATTACHED and config.key == key
    ]


def create(scene: bpy.types.Scene, config: BindingConfig, name: str) -> str:
    """Make a binding with bindings.create, and record it; it has no manifest yet. Returns its identifier.

    Raises NotTracking before changing anything, and what bindings.create raises.
    """
    state = _current()
    binding_id, config = bindings.create(scene, config, name)
    made = _Binding(scene, scene.session_uid, config, None)
    state.bindings[binding_id] = [made]
    assert config.destination is not None
    uid = config.destination.session_uid
    state.by_destination.setdefault(uid, []).append((binding_id, made))  # last, as among the bindings
    state.identities[binding_id] = candidates.Identity([], [Candidate(uid, mutual=True)], [uid], _UNIQUE)
    state.tagged |= {uid}
    return binding_id


def set_config(binding_id: str, config: BindingConfig) -> None:
    """Store a binding's changed configuration; an unchanged one writes nothing.

    Raises RecordRefused, changing nothing, over one that can't be read; KeyError if there's no such binding.
    """
    found = _existing(binding_id)
    if config == found.config:
        return
    bindings.update(found.scene, binding_id, config)
    moved = isinstance(found.config, Refused) or found.config.destination != config.destination
    found.config = config
    if moved:  # a destination changes only in repair: rebuilt whole, in the order a rebuild finds
        invalidate()
        return
    _restore_entry(binding_id, found)


# Manifests and ownership.


def manifest(binding_id: str) -> Loaded[Manifest] | Refused | None:
    """A binding's manifest, read through its configuration's destination when first asked for.

    Refused if the configuration or the manifest can't be read; None if the binding has no
    destination (it was removed) or no manifest yet. Raises KeyError if no binding has this identifier.
    """
    found = _existing(binding_id)
    return _checked_manifest(_current(), binding_id, found)


def set_manifest(binding_id: str, manifest: Manifest) -> None:
    """Store a binding's manifest on its destination, replacing only that destination's share of ownership.

    Raises RecordRefused, changing nothing, over one that can't be read; KeyError if there's no such
    binding; ValueError if it has no destination.
    """
    found = _existing(binding_id)
    destination = _destination(binding_id, found)
    ownership.write_manifest(destination, manifest)
    _replace_manifest(_current(), binding_id, destination, Loaded(manifest, ownership.MANIFEST.version))
    _restore_entry(binding_id, found)


def update_manifest(binding_id: str, changed: Mapping[str, ManifestEntry], removed: Collection[str] = ()) -> None:
    """Change some of a binding's manifest entries, writing only those: changed adds or replaces entries by
    resource identity, and removed deletes them. A binding with no manifest yet starts from an empty one,
    and an empty update writes nothing. What it writes and indexes is what changes; in memory it also
    copies the manifest's entries and, with removals, scans their uses (Manifest.updated).

    Raises what set_manifest raises, and ValueError, TypeError, or KeyError (ownership.write_entries),
    changing nothing, over an update that makes no manifest.
    """
    # Read once: the checks, the record, and the index each go through it, so a one-shot iterable would leave
    # them disagreeing, and Manifest.updated tests it once per entry and per use.
    removed = frozenset(removed)
    found, destination, current = _to_update(binding_id)
    if not changed and not removed:
        return
    # Built first through _ask, which rebuilds the state if any destination was removed; then looked up again.
    _ask(_ownership)
    found, destination, current = _to_update(binding_id)
    state = _current()
    index = state.ownership
    assert index is not None
    share = index.shares[destination.session_uid]
    before = Manifest({}) if current is None else current.record
    after = before.updated(changed, removed, lambda uid: c.resource_id if (c := share.claims.get(uid)) else None)
    ownership.write_entries(destination, after, changed.keys(), removed)
    _give_manifest(state, destination, Loaded(after, ownership.MANIFEST.version))
    keys = [*changed, *removed]
    for resource_id in keys:
        _remove_claim(index, share, resource_id)
    for resource_id in changed:
        if (datablock := after.entries[resource_id].datablock) is not None:
            _add_claim(index, share, datablock, Claim(share.claimant, destination, resource_id))
    _restore_entry(binding_id, found)


def claims_on(datablock: bpy.types.ID) -> list[Claim]:
    """The claims on datablock; none if it is unmanaged (ownership.Claim says what they mean)."""
    return _ask(lambda state: _checked_claims(state, datablock))


def resource(binding_id: str, resource_id: str) -> bpy.types.ID | None:
    """The datablock of a binding's resource, as its manifest names it; None if it names none, or the binding
    has no destination or manifest. Reads only that binding's manifest, not the ownership index."""
    return _ask(lambda state: _checked_resource(state, binding_id, resource_id))


def unreadable_manifests() -> list[Refused]:
    return _ask(lambda state: list(_ownership(state).unreadable.values()))


# The state. Every lookup is a question _ask puts to it: a check that finds a scene or destination gone
# raises _Stale, and _ask rebuilds the state and asks once more.


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
        found = _read_bindings()
        copies = candidates.find({b: [(c.scene, c.config) for c in cs] for b, cs in found.items()})
        _state = _State(scenes, found, _by_destination(found), copies.identities, copies.tagged)
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
    uid = None if scene is None else scene.session_uid
    listed = []
    for binding_id, found in state.bindings.items():
        if uid is not None and all(b.scene_uid != uid for b in found):
            continue  # none on scene, so it can't be listed there, whatever the rule decides: not checked
        _check_candidates(state, binding_id, found)
        canonical = state.identities[binding_id].decision.canonical
        here = found if canonical is None else [found[canonical]]
        if uid is None or any(b.scene_uid == uid for b in here):
            listed.append(binding_id)
    return listed


def _configs(state: _State) -> dict[str, BindingConfig | Refused | CopiedBinding]:
    configs: dict[str, BindingConfig | Refused | CopiedBinding] = {}
    for binding_id in state.bindings:
        try:
            canonical = _canonical(state, binding_id)
        except Disabled as disabled:
            configs[binding_id] = disabled.report
        else:
            assert canonical is not None
            configs[binding_id] = canonical.config
    return configs


def _copied(state: _State) -> list[CopiedBinding]:
    copied = []
    for binding_id, identity in state.identities.items():
        if identity.decision.reason is not Reason.UNIQUE:
            found = state.bindings.get(binding_id, [])
            _check_candidates(state, binding_id, found)
            copied.append(candidates.report(binding_id, identity, [(b.scene, b.config) for b in found]))
    return copied


def _canonical(state: _State, binding_id: str) -> _Binding | None:
    """The binding's canonical candidate, every candidate checked (see _valid), or None if no binding has this
    identifier. Raises Disabled if it has none."""
    found = state.bindings.get(binding_id)
    if found is None:
        return None
    _check_candidates(state, binding_id, found)
    identity = state.identities[binding_id]
    if (canonical := identity.decision.canonical) is None:
        raise Disabled(candidates.report(binding_id, identity, [(b.scene, b.config) for b in found]))
    return found[canonical]  # a record: copies are never mutual, so with records the rule picks one


def _check_candidates(state: _State, binding_id: str, found: list[_Binding]) -> None:
    """Raise _Stale if any candidate of the identity is gone: the rule's decision may have been different."""
    copies = state.identities[binding_id].copies
    if not all(_valid(binding_id, b) for b in found) or not all(
        _alive(c) and records.has(c, bindings.TAG_KEY) for c in copies
    ):
        raise _Stale


def _restore_entry(binding_id: str, found: _Binding) -> None:
    """After a write to the canonical candidate's records: restore its index entry if the index has none for it
    and its record and destination refer to each other (source-access.md#canonical-candidate). Detection
    writes nothing; a file with two indexes, or one that can't be read, is left as it is."""
    identity = _current().identities[binding_id]
    if identity.entries or isinstance(found.config, Refused) or found.config.destination is None:
        return
    if not candidates.refers_back(binding_id, found.scene, found.config):
        return
    try:
        bindings.restore_entry(binding_id, found.config.destination)
    except (ValueError, RecordRefused):
        return
    identity.restored(found.config.destination)


def _to_update(binding_id: str) -> tuple[_Binding, bpy.types.Collection, Loaded[Manifest] | None]:
    """The binding, its destination, and its manifest, for update_manifest. Raises as update_manifest does."""
    found = _existing(binding_id)
    destination = _destination(binding_id, found)
    # Unchecked, which would cost the manifest: an entry naming a removed datablock is carried into the result,
    # whose next check rereads it, and its claim, under a session_uid no other datablock gets, stays unfound.
    current = _manifest_of(found)
    if isinstance(current, Refused):
        raise RecordRefused(current)
    return found, destination, current


def _existing(binding_id: str) -> _Binding:
    if (found := _ask(lambda state: _canonical(state, binding_id))) is None:
        raise KeyError(binding_id)
    return found


def _destination(binding_id: str, binding: _Binding) -> bpy.types.Collection:
    if isinstance(binding.config, Refused) or binding.config.destination is None:
        raise ValueError(f"binding {binding_id} has no destination to hold a manifest")
    return binding.config.destination


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


def _checked_manifest(state: _State, binding_id: str, binding: _Binding) -> Loaded[Manifest] | Refused | None:
    """The binding's manifest, reread if a datablock it names was removed; Blender cleared that entry's pointer."""
    found = _manifest_of(binding)
    if isinstance(found, Loaded) and not all(
        e.datablock is None or _alive(e.datablock) for e in found.record.entries.values()
    ):
        assert not isinstance(binding.config, Refused) and binding.config.destination is not None
        found = _reread(state, binding_id, binding.config.destination)
    return found


def _reread(state: _State, binding_id: str, destination: bpy.types.Collection) -> Loaded[Manifest] | Refused | None:
    """Reread a destination's manifest after a datablock it names was removed, replacing its share alone."""
    found = ownership.read_manifest(destination)
    _replace_manifest(state, binding_id, destination, found)
    return found


def _replace_manifest(
    state: _State, binding_id: str, destination: bpy.types.Collection, manifest: Loaded[Manifest] | Refused | None
) -> None:
    """Give the manifest to every configuration naming the destination, and replace the destination's share
    of ownership, keeping its claimant (binding_id's, if it has no share yet)."""
    _give_manifest(state, destination, manifest)
    if (index := state.ownership) is not None:
        uid = destination.session_uid
        share = index.shares.get(uid)
        _remove_share(index, uid)
        _add_share(index, binding_id if share is None else share.claimant, destination, manifest)


def _give_manifest(
    state: _State, destination: bpy.types.Collection, manifest: Loaded[Manifest] | Refused | None
) -> None:
    """Give the manifest to every configuration naming the destination, as a linked copy's does."""
    for _, b in state.by_destination.get(destination.session_uid, ()):
        b.manifest = manifest


def _by_destination(candidates_by_id: dict[str, list[_Binding]]) -> dict[int, list[tuple[str, _Binding]]]:
    """Every candidate naming a destination, by its session_uid, in the order found; a removed one is left out,
    and the check of the candidates naming it rebuilds the state."""
    found: dict[int, list[tuple[str, _Binding]]] = {}
    for binding_id, found_for_id in candidates_by_id.items():
        for b in found_for_id:
            if not isinstance(b.config, Refused) and b.config.destination is not None and _alive(b.config.destination):
                found.setdefault(b.config.destination.session_uid, []).append((binding_id, b))
    return found


def _ownership(state: _State) -> _Ownership:
    """The ownership index, built from every candidate's manifest if it isn't.

    Each destination counts once, though several configurations can name it, with the first binding
    found whose configuration names it as the claimant; a tagged collection no record names claims
    for the binding its tag names.
    """
    if state.ownership is None:
        index = _Ownership({}, {}, {})
        for named in state.by_destination.values():
            binding_id, b = named[0]
            assert not isinstance(b.config, Refused) and b.config.destination is not None
            if not _alive(b.config.destination):
                raise _Stale  # removed since the state was built: Blender cleared the configurations' pointers
            _add_share(index, binding_id, b.config.destination, _checked_manifest(state, binding_id, b))
        for binding_id, identity in state.identities.items():  # tagged collections no record names
            for copy in identity.copies:
                if not _alive(copy):
                    raise _Stale
                _add_share(index, binding_id, copy, ownership.read_manifest(copy))
        state.ownership = index
    return state.ownership


def _add_share(
    index: _Ownership, claimant: str, destination: bpy.types.Collection, manifest: Loaded[Manifest] | Refused | None
) -> None:
    uid = destination.session_uid
    share = _Share(claimant, {}, {})
    if isinstance(manifest, Refused):
        index.unreadable[uid] = manifest  # claims nothing until it is repaired
    elif manifest is not None:
        for resource_id, entry in manifest.record.entries.items():
            if entry.datablock is not None:
                _add_claim(index, share, entry.datablock, Claim(claimant, destination, resource_id))
    index.shares[uid] = share


def _remove_share(index: _Ownership, uid: int) -> None:
    if (share := index.shares.pop(uid, None)) is None:
        return
    for resource_id in list(share.entries):
        _remove_claim(index, share, resource_id)
    index.unreadable.pop(uid, None)


def _add_claim(index: _Ownership, share: _Share, datablock: bpy.types.ID, claim: Claim) -> None:
    datablock_uid = datablock.session_uid
    if (found := index.claims.get(datablock_uid)) is None:
        index.claims[datablock_uid] = claim
    else:
        index.claims[datablock_uid] = (*_as_tuple(found), claim)
    share.claims[datablock_uid] = claim
    share.entries[claim.resource_id] = datablock_uid


def _remove_claim(index: _Ownership, share: _Share, resource_id: str) -> None:
    """Take out the claim of the share's entry for resource_id, if it names a datablock."""
    if (datablock_uid := share.entries.pop(resource_id, None)) is None:
        return
    claim = share.claims.pop(datablock_uid)
    remaining = tuple(c for c in _as_tuple(index.claims[datablock_uid]) if c is not claim)
    if not remaining:
        del index.claims[datablock_uid]
    else:
        index.claims[datablock_uid] = remaining[0] if len(remaining) == 1 else remaining


def _checked_claims(state: _State, datablock: bpy.types.ID) -> list[Claim]:
    found = _ownership(state).claims.get(datablock.session_uid)
    claims = [] if found is None else list(_as_tuple(found))
    if not all(_alive(claim.destination) for claim in claims):
        raise _Stale
    return claims


def _as_tuple(claims: Claim | tuple[Claim, ...]) -> tuple[Claim, ...]:
    return claims if isinstance(claims, tuple) else (claims,)


def _checked_resource(state: _State, binding_id: str, resource_id: str) -> bpy.types.ID | None:
    """Through the manifest of the binding's canonical candidate, checked as every lookup by identity is."""
    if (first := _canonical(state, binding_id)) is None:
        return None
    datablock = _named(_manifest_of(first), resource_id)
    if datablock is not None and not _alive(datablock):
        # Removed: its manifest is reread, where Blender has cleared the entry, and its share replaced.
        assert not isinstance(first.config, Refused) and first.config.destination is not None
        datablock = _named(_reread(state, binding_id, first.config.destination), resource_id)
        if datablock is not None and not _alive(datablock):
            raise _Stale
    return datablock


def _named(manifest: Loaded[Manifest] | Refused | None, resource_id: str) -> bpy.types.ID | None:
    entry = manifest.record.entries.get(resource_id) if isinstance(manifest, Loaded) else None
    return None if entry is None else entry.datablock


def _alive(id_: bpy.types.ID) -> bool:
    try:
        id_.name  # noqa: B018 - touching a removed ID's reference raises
    except ReferenceError:
        return False
    return True
