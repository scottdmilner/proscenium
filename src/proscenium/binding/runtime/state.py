"""The bindings' in-memory state, a disposable cache of their records (lifecycle.md#undo-and-runtime-state).

It holds two things:

- The records, decoded, each once and held as they are stored, by the datablock holding them: each destination
  collection's binding records and, once read, its manifest (DestinationRecords), and each Text's binding index and,
  once read, its pending-cleanup ledger (IndexRecords).
- What is computed from them: each binding identity's candidates and the canonical-candidate rule's decision
  (copy_detection.IdentityCandidates), whose binding records are read through their collections' (BindingRecord), and
  the ownership index (ownership_index), built when first asked for.

binding_configs looks bindings up in it, and ownership_index builds the claims on each datablock from it.

How it stays current:

- Writes go through it, writing the stored record and holding what the write stored, so nothing is read back from
  the records. A write that changes what the rule reads decides that identity again.
- A file load, undo, or redo changes the records behind it. The extension's handlers drop the state before and after
  each, and the next use rebuilds it; dropping it before means another extension's handler that runs first reads
  the new data. So the state needs the extension registered (NotRegisteredError).
- Scenes added or removed, as a scene copy, a new scene, or an append makes them, have no handler: each use compares
  the scenes' session_uids with those the state was built from. Removing a target scene removes its bindings.
- Content appended or linked, and a collection duplicated on its own, add no scene: refresh_if_records_changed() finds
  them, as a synchronization asks it to first, and otherwise the next load, undo, or redo does.

What it holds:

- References to IDs only, never to structs inside one (modifiers, mesh elements, nodes): Blender invalidates a
  removed ID's Python reference, but a struct held across undo silently reads freed memory.
- Each reference is checked before it's returned (alive()), since the user can remove content at any time. A removed
  scene or destination, which removes a binding, raises StaleError, and query() rebuilds the state and asks again; a
  removed managed datablock rereads only the manifest naming it (ownership_index).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import bpy

from ..persistence import configs, records
from . import copy_detection

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..persistence import ledgers, manifests
    from ..source_access import identifiers
    from .copy_detection import IdentityCandidates
    from .ownership_index import OwnershipIndex

_tracking = False  # whether the extension's handlers are registered, so the state is kept current
_state: State | None = None
_rebuilds = 0  # how many times the state was dropped or rebuilt; see rebuild_count()


class NotRegisteredError(RuntimeError):  # a precondition, raised like RuntimeError
    """The bindings' state was used without the extension registered, whose handlers keep it current."""


class StaleError(Exception):
    """A reference the state holds is gone."""


class Unread:
    """A manifest not read yet."""


UNREAD = Unread()


type HeldConfig = configs.BindingConfig | records.RefusedRecord  # a configuration, or why it can't be read


@dataclass(slots=True)
class DestinationRecords:
    """The records on a collection holding binding records: its configurations, and its manifest once read."""

    collection: bpy.types.Collection
    configs: dict[identifiers.BindingId, HeldConfig] = field(default_factory=dict)  # normally one
    manifest: records.Loaded[manifests.Manifest] | records.RefusedRecord | None | Unread = UNREAD

    def records_found(self) -> list[BindingRecord]:
        """Its binding records, in the order found."""
        return [BindingRecord(self, binding_id) for binding_id in self.configs]


@dataclass(frozen=True, slots=True)
class BindingRecord:
    """One collection's binding record for a binding identity, read through its records, so a write reaches it."""

    held: DestinationRecords
    binding_id: identifiers.BindingId

    @property
    def collection(self) -> bpy.types.Collection:
        """The collection holding the record: the binding's destination."""
        return self.held.collection

    @property
    def config(self) -> HeldConfig:
        """The configuration, or why it can't be read."""
        return self.held.configs[self.binding_id]

    @property
    def scene(self) -> bpy.types.Scene | None:
        """The target scene a readable configuration names; None for one that can't be read, or a removed scene."""
        return None if isinstance(self.config, records.RefusedRecord) else self.config.scene

    @property
    def candidate(self) -> bool:
        """Whether it's a candidate of its identity: unreadable, or naming a target scene that exists."""
        return isinstance(self.config, records.RefusedRecord) or self.config.scene is not None


@dataclass(slots=True)
class IndexRecords:
    """The records on a Text holding a binding index: the index, and the pending-cleanup ledger once read."""

    text: bpy.types.Text
    index: configs.BindingIndex | records.RefusedRecord
    ledger: records.Loaded[ledgers.Ledger] | records.RefusedRecord | None | Unread = UNREAD


@dataclass(slots=True)
class State:
    """The bindings' state, built from the records (the module docstring says how it's kept)."""

    scene_uids: tuple[int, ...]  # the session_uids of every scene it was built from, in order: compared at each use
    # The records, each held once, by the datablock holding them, in the order found.
    destinations: dict[int, DestinationRecords]  # by session_uid: every local collection with binding records
    indexes: list[IndexRecords]  # every local Text with a binding index; a file normally has one
    # Computed from the records.
    identities: dict[identifiers.BindingId, IdentityCandidates]  # every identity with a candidate
    ownership: OwnershipIndex | None = None  # built when first asked for

    @property
    def binding_uids(self) -> frozenset[int]:
        """The session_uids of the collections holding binding records (refresh_if_records_changed)."""
        return frozenset(self.destinations)

    def add_binding(self, created: configs.CreatedBinding) -> None:
        """Hold a binding just made: the records create stored, and its identity's decision."""
        binding_id, destination = created.binding_id, created.destination
        held = DestinationRecords(destination, {binding_id: created.config}, None)
        self.destinations[destination.session_uid] = held
        self._hold_index(created.index)
        self.identities[binding_id] = copy_detection.identity(self, binding_id, [BindingRecord(held, binding_id)])

    def replace_index(self, binding_id: identifiers.BindingId, written: configs.WrittenIndex) -> None:
        """Hold the binding index a write stored with binding_id's entry, and decide that identity again.

        A write to the index refuses a file with more than one, so the file now has only this one.
        """
        self._hold_index(written)
        identity = self.identities[binding_id]
        self.identities[binding_id] = copy_detection.identity(self, binding_id, identity.candidates)

    def _hold_index(self, written: configs.WrittenIndex) -> None:
        """Hold the only binding index, keeping the ledger held from its Text, which the write left as it was."""
        ledger = next((i.ledger for i in self.indexes if i.text == written.text), UNREAD)
        self.indexes = [IndexRecords(written.text, written.index, ledger)]


def start_tracking() -> None:
    """The extension registered its handlers: the state can be used."""
    global _tracking
    _tracking = True
    invalidate()


def stop_tracking() -> None:
    """The extension unregistered its handlers: the state can't be used until start_tracking()."""
    global _tracking
    _tracking = False
    invalidate()


def invalidate() -> None:
    """Drop the state, after a file load, undo, or redo: the next use rebuilds it from the records."""
    global _state, _rebuilds
    _state = None
    _rebuilds += 1


def rebuild_count() -> int:
    """A number that changes whenever the state is dropped or rebuilt.

    Runtime state kept beside the bindings, such as their stages (CurrentStages), compares it to tell when the bindings
    may have changed: after a load, undo, or redo, or when scenes are added or removed.
    """
    return _rebuilds


def refresh_if_records_changed() -> None:
    """Rebuild the state if the local collections holding binding records changed since it was built.

    Duplicating a collection on its own changes them, which no handler announces. Checks every collection's records.
    """
    if _state is not None and configs.binding_uids() != _state.binding_uids:
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
    if _state is None or _state.scene_uids != scenes:
        _state = _read_state(scenes)
        _rebuilds += 1
    return _state


def valid(binding_id: identifiers.BindingId, record: BindingRecord) -> bool:
    """Whether the record's collection still exists and holds its configuration, and its target scene still exists.

    Removing the target scene clears the configuration's pointer to it.
    """
    scene = record.scene
    return (
        alive(record.collection)
        and configs.has_config(record.collection, binding_id)
        and (scene is None or alive(scene))
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


def _read_state(scenes: tuple[int, ...]) -> State:
    """Read every binding record and binding index, and decide every identity."""
    destinations: dict[int, DestinationRecords] = {}
    for collection, binding_id, result in configs.read_configs():
        held = destinations.setdefault(collection.session_uid, DestinationRecords(collection))
        held.configs[binding_id] = result if isinstance(result, records.RefusedRecord) else result.record
    indexes = []
    for text in configs.index_texts():
        index = configs.read_index(text)
        assert index is not None  # index_texts found the record
        indexes.append(IndexRecords(text, index.record if isinstance(index, records.Loaded) else index))
    current = State(scenes, destinations, indexes, {})
    current.identities = copy_detection.identities(current)
    return current
