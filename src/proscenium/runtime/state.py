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
add no scene, so they're seen at the next load, undo, or redo, or when refresh_if_tags_changed()
finds the collections' tags changed, as a synchronization asks it to first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy

from ..core.canonical_candidate import CandidateEvidence, CanonicalDecision, DecisionReason
from ..persistence import binding_records, records
from ..persistence.records import RefusedRecord
from . import copy_detection

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..core.binding_ids import BindingId
    from ..persistence.binding_records import BindingConfig
    from ..persistence.manifests import Manifest
    from ..persistence.records import Loaded
    from .copy_detection import IdentityCandidates
    from .ownership_index import OwnershipIndex

_tracking = False  # whether the extension's handlers are registered, so the state is kept current
_state: State | None = None
_rebuilds = 0  # how many times the state was dropped or rebuilt; see rebuild_count()
_UNIQUE = CanonicalDecision(0, DecisionReason.UNIQUE)


class NotRegisteredError(RuntimeError):  # a precondition, raised like RuntimeError
    """The bindings' state was used without the extension registered, whose handlers keep it current."""


class StaleError(Exception):
    """A reference the state holds is gone."""


class Unread:
    """A manifest not read yet."""


UNREAD = Unread()


@dataclass(slots=True)
class Candidate:
    """One binding record of a binding identity: a scene's configuration for it, and its manifest once read."""

    scene: bpy.types.Scene
    scene_uid: int  # compared instead of the reference: a new scene can take a removed one's address
    config: BindingConfig | RefusedRecord
    manifest: Loaded[Manifest] | RefusedRecord | None | Unread = UNREAD


@dataclass(slots=True)
class State:
    """The bindings' state, built from the records (the module docstring says how it's kept)."""

    scenes: tuple[int, ...]  # the session_uids of the scenes it was built from, in order
    # Every identity with a record or a tagged collection, in the order found: its candidates and the rule's decision.
    identities: dict[BindingId, IdentityCandidates]
    # By destination session_uid: the records whose configuration names it, with their identifiers, in the
    # order found, so a write reaches them without going through every binding (_by_destination).
    by_destination: dict[int, list[tuple[BindingId, Candidate]]]
    tagged: frozenset[int]  # the session_uids of the tagged collections it was built from (refresh_if_tags_changed)
    ownership: OwnershipIndex | None = None  # built when first asked for

    def add_binding(self, binding_id: BindingId, record: Candidate) -> None:
        """Add a binding just made: its one record, whose destination's tag and index entry name it, so it's unique."""
        assert not isinstance(record.config, RefusedRecord) and record.config.destination is not None
        uid = record.config.destination.session_uid
        self.identities[binding_id] = copy_detection.IdentityCandidates(
            [record], [], [CandidateEvidence(uid, mutual=True)], [uid], _UNIQUE
        )
        self.by_destination.setdefault(uid, []).append((binding_id, record))  # last, where a rebuild finds it
        self.tagged |= {uid}

    def cache_manifest(
        self, destination: bpy.types.Collection, manifest: Loaded[Manifest] | RefusedRecord | None
    ) -> None:
        """Give the destination's manifest to every record naming it, as a linked copy's records do."""
        for _, record in self.by_destination.get(destination.session_uid, ()):
            record.manifest = manifest


def start() -> None:
    """The extension registered its handlers: the state can be used."""
    global _tracking
    _tracking = True
    invalidate()


def stop() -> None:
    """The extension unregistered its handlers: the state can't be used until start()."""
    global _tracking
    _tracking = False
    invalidate()


def invalidate() -> None:
    """Drop the state, after a file load, undo, or redo: the next use rebuilds it from the records."""
    global _state, _rebuilds
    _state = None
    _rebuilds += 1


def rebuild_count() -> int:
    """A count that changes whenever the state is dropped or rebuilt from the records.

    It changes after a load, undo, or redo, and when scenes are added or removed, so runtime state keyed by binding
    identity, such as the bindings' stages, knows to compare its bindings with binding_ids().
    """
    return _rebuilds


def refresh_if_tags_changed() -> None:
    """Rebuild the state if the local collections' destination tags changed since it was built.

    Duplicating a collection on its own changes them, which no handler announces. Checks every collection's records.
    """
    if _state is not None and binding_records.tagged_uids() != _state.tagged:
        invalidate()


# Every lookup is a question query() puts to the state: a check that finds a scene or destination gone raises
# StaleError, and query() rebuilds the state and asks once more.


def query[T](question: Callable[[State], T]) -> T:
    """The answer to question; if a reference it reaches is gone, the state is rebuilt and asked once more."""
    try:
        return question(current_state())
    except StaleError:
        invalidate()
        return question(current_state())


def current_state() -> State:
    """The state, rebuilt from the records if it was dropped or the scenes changed.

    Raises NotRegisteredError if the extension isn't registered.
    """
    global _state, _rebuilds
    if not _tracking:
        raise NotRegisteredError("the extension isn't registered, so the bindings' state can't be kept current")
    scenes = _scene_uids()
    if _state is None or _state.scenes != scenes:
        detected = copy_detection.detect(_read_candidates())
        _state = State(scenes, detected.identities, _by_destination(detected.identities), detected.tagged)
        _rebuilds += 1
    return _state


def valid(binding_id: BindingId, candidate: Candidate) -> bool:
    """Whether the candidate's scene still exists and holds its configuration, and its destination still exists.

    Removing a destination clears the configuration's pointer to it.
    """
    destination = None if isinstance(candidate.config, RefusedRecord) else candidate.config.destination
    return (
        alive(candidate.scene)
        and records.has(candidate.scene, binding_records.config_key(binding_id))
        and (destination is None or alive(destination))
    )


def alive(id_: bpy.types.ID) -> bool:
    """Whether the ID still exists: touching a removed one's reference raises."""
    try:
        id_.name  # noqa: B018 - touching a removed ID's reference raises
    except ReferenceError:
        return False
    return True


def _scene_uids() -> tuple[int, ...]:
    return tuple(scene.session_uid for scene in bpy.data.scenes)


def _read_candidates() -> dict[BindingId, list[Candidate]]:
    candidates: dict[BindingId, list[Candidate]] = {}
    for scene, binding_id, result in binding_records.read_configs():
        config = result if isinstance(result, RefusedRecord) else result.record
        candidates.setdefault(binding_id, []).append(Candidate(scene, scene.session_uid, config))
    return candidates


def _by_destination(identities: dict[BindingId, IdentityCandidates]) -> dict[int, list[tuple[BindingId, Candidate]]]:
    """Every record naming a destination, by its session_uid, in the order found.

    A removed destination's records are left out, and checking them rebuilds the state.
    """
    by_uid: dict[int, list[tuple[BindingId, Candidate]]] = {}
    for binding_id, identity in identities.items():
        for candidate in identity.records:
            config = candidate.config
            if not isinstance(config, RefusedRecord) and config.destination is not None and alive(config.destination):
                by_uid.setdefault(config.destination.session_uid, []).append((binding_id, candidate))
    return by_uid
