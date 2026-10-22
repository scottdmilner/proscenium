"""The bindings' in-memory state, which the runtime indexes are built into (lifecycle.md#undo-and-runtime-state).

This state is a disposable write-through cache of the bindings' records: each binding's scene and
decoded configuration, and, read when first needed, its decoded manifest, with every datablock's
claims (proscenium.runtime.ownership_index). It holds every candidate of an identity (source-
access.md#copied-bindings), and the canonical-candidate rule's decision on them
(proscenium.runtime.copy_detection); lookups by identity are proscenium.runtime.binding_configs'. The extension's
writes go through it, updating memory and writing the records at once, since the records are what's
saved and what undo steps capture. So nothing is read back from the records after the extension's own
writes.

The records change behind the state only when Blender changes data: a file load, undo, or redo.
The extension's handlers for those drop the state, before and after, and the next use rebuilds it
from the records; dropping it before means another extension's handler that runs ahead of these
reads the new data. That's why the state needs the extension registered: without the handlers, a
binding that redo brings back would never be found. Scenes added or removed, as a scene copy, a new
scene, or an append makes them, no handler announces: every use compares the scenes' session_uids
with those the state was built from, and rebuilds if they differ.

The state holds datablock references, which Blender invalidates under it: undo re-reads every
datablock the undone step changed, which a synchronization's managed content always is, and a file
load frees every one. Those come with a rebuild. The user may also remove content at any time, which
no handler announces, so every hit is checked before it's returned (a removed ID's reference raises
when touched, alive()). A removed scene or destination clears pointers in the configurations, so a
check that finds one gone raises StaleError, and query() rebuilds the state and asks again; a removed
managed datablock costs less (proscenium.runtime.ownership_index). Only ID references are held, never
the structs inside a datablock (modifiers, mesh elements, nodes): Blender invalidates a removed ID's
Python reference but not those, and one held across undo silently reads freed memory.

Other content brought in by append or link, and a destination collection duplicated on its own,
add no scene, so they're seen at the next load, undo, or redo, or when find_copies() finds the
collections' tags changed, as a synchronization asks it to first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy

from ..persistence import binding_records, records
from ..persistence.records import RefusedRecord
from . import copy_detection

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..persistence.binding_records import BindingConfig
    from ..persistence.manifests import Manifest
    from ..persistence.records import Loaded
    from .ownership_index import OwnershipIndex

_tracking = False  # whether the extension's handlers are registered, so the state is kept current
_state: State | None = None
_rebuilds = 0  # how many times the state was dropped or rebuilt; see rebuilds()


class NotRegisteredError(RuntimeError):  # a precondition, raised like RuntimeError
    """The bindings' state was used without the extension registered, whose handlers keep it current."""


class StaleError(Exception):
    """A reference the state holds is gone."""


class Unread:
    """A manifest not read yet."""


UNREAD = Unread()


@dataclass(slots=True)
class Candidate:
    """One candidate of a binding identity: a scene's configuration record for it."""

    scene: bpy.types.Scene
    scene_uid: int  # compared instead of the reference: a new scene can take a removed one's address
    config: BindingConfig | RefusedRecord
    manifest: Loaded[Manifest] | RefusedRecord | None | Unread = UNREAD


@dataclass(slots=True)
class State:
    scenes: tuple[int, ...]  # the session_uids of the scenes it was built from, in order
    bindings: dict[str, list[Candidate]]  # by binding identifier: its candidates, in the order found
    # By destination session_uid: the candidates whose configuration names it, with their identifiers, in the
    # order found, so a write reaches them without going through every binding (_by_destination).
    by_destination: dict[int, list[tuple[str, Candidate]]]
    identities: dict[
        str, copy_detection.IdentityCandidates
    ]  # by binding identifier: its candidates, as the rule reads them
    tagged: frozenset[int]  # the session_uids of the tagged collections it was built from (find_copies)
    ownership: OwnershipIndex | None = None  # built when first asked for


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
    identity, such as the bindings' stages, knows to compare its bindings with binding_ids()."""
    return _rebuilds


def find_copies() -> None:
    """Rebuild the state if the local collections' destination tags changed since it was built, as duplicating
    a collection on its own changes them, which no handler announces. Checks every collection's records."""
    if _state is not None and binding_records.tagged_uids() != _state.tagged:
        invalidate()


# Every lookup is a question query() puts to the state: a check that finds a scene or destination gone raises
# StaleError, and query() rebuilds the state and asks once more.


def query[T](question: Callable[[State], T]) -> T:
    try:
        return question(current_state())
    except StaleError:
        invalidate()
        return question(current_state())


def current_state() -> State:
    global _state, _rebuilds
    if not _tracking:
        raise NotRegisteredError("the extension isn't registered, so the bindings' state can't be kept current")
    scenes = _scene_uids()
    if _state is None or _state.scenes != scenes:
        found = _read_bindings()
        detected = copy_detection.detect({b: [(c.scene, c.config) for c in cs] for b, cs in found.items()})
        _state = State(scenes, found, _by_destination(found), detected.identities, detected.tagged)
        _rebuilds += 1
    return _state


def valid(binding_id: str, binding: Candidate) -> bool:
    """Whether the candidate's scene still exists and holds its configuration, and its destination still
    exists; removing a destination clears the configuration's pointer to it."""
    destination = None if isinstance(binding.config, RefusedRecord) else binding.config.destination
    return (
        alive(binding.scene)
        and records.has(binding.scene, binding_records.config_key(binding_id))
        and (destination is None or alive(destination))
    )


def alive(id_: bpy.types.ID) -> bool:
    try:
        id_.name  # noqa: B018 - touching a removed ID's reference raises
    except ReferenceError:
        return False
    return True


def _scene_uids() -> tuple[int, ...]:
    return tuple(scene.session_uid for scene in bpy.data.scenes)


def _read_bindings() -> dict[str, list[Candidate]]:
    found: dict[str, list[Candidate]] = {}
    for scene, binding_id, result in binding_records.config_records():
        config = result if isinstance(result, RefusedRecord) else result.record
        found.setdefault(binding_id, []).append(Candidate(scene, scene.session_uid, config))
    return found


def _by_destination(candidates_by_id: dict[str, list[Candidate]]) -> dict[int, list[tuple[str, Candidate]]]:
    """Every candidate naming a destination, by its session_uid, in the order found; a removed one is left out,
    and the check of the candidates naming it rebuilds the state."""
    found: dict[int, list[tuple[str, Candidate]]] = {}
    for binding_id, found_for_id in candidates_by_id.items():
        for b in found_for_id:
            if (
                not isinstance(b.config, RefusedRecord)
                and b.config.destination is not None
                and alive(b.config.destination)
            ):
                found.setdefault(b.config.destination.session_uid, []).append((binding_id, b))
    return found
