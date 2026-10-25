"""The bindings' in-memory state, a disposable cache of their records (lifecycle.md#undo-and-runtime-state).

It holds two things:

- The records, decoded, each once and held as they are stored, by the datablock holding them: each scene's binding
  records (SceneRecords), each destination collection's tag and, once read, its manifest (DestinationRecords), and
  each Text's binding index (IndexRecords).
- What is computed from them: each binding identity's candidates and the canonical-candidate rule's decision
  (copy_detection.IdentityCandidates), whose binding records are read through their scenes' (BindingRecord), and the
  ownership index (ownership_index), built when first asked for.

binding_configs looks bindings up in it, and ownership_index builds the claims on each datablock from it.

How it stays current:

- Writes go through it, writing the stored record and holding what the write stored, so nothing is read back from
  the records. A write that changes what the rule reads decides that identity again.
- A file load, undo, or redo changes the records behind it. The extension's handlers drop the state before and after
  each, and the next use rebuilds it; dropping it before means another extension's handler that runs first reads
  the new data. So the state needs the extension registered (NotRegisteredError).
- Scenes added or removed, as a scene copy, a new scene, or an append makes them, have no handler: each use compares
  the scenes' session_uids with those the state was built from.
- Content appended or linked, and a collection duplicated on its own, add no scene: refresh_if_tags_changed() finds
  them, as a synchronization asks it to first, and otherwise the next load, undo, or redo does.

What it holds:

- References to IDs only, never to structs inside one (modifiers, mesh elements, nodes): Blender invalidates a
  removed ID's Python reference, but a struct held across undo silently reads freed memory.
- Each reference is checked before it's returned (alive()), since the user can remove content at any time. A removed
  scene or destination raises StaleError, and query() rebuilds the state and asks again; a removed managed datablock
  rereads only the manifest naming it (ownership_index).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import bpy

from ..persistence import binding_records, records
from ..persistence.binding_records import BindingConfig
from ..persistence.records import Loaded, RefusedRecord
from . import copy_detection

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..core.binding_ids import BindingId
    from ..persistence.binding_records import BindingIndex, CreatedBinding, DestinationTag, WrittenIndex
    from ..persistence.manifests import Manifest
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


@dataclass(slots=True)
class SceneRecords:
    """The binding records on a scene: by binding identity, the configuration stored there."""

    scene: bpy.types.Scene
    uid: int  # its session_uid, compared instead of the reference: a new scene can take a removed one's address
    configs: dict[BindingId, BindingConfig | RefusedRecord] = field(default_factory=dict)

    def records(self) -> list[BindingRecord]:
        """Its binding records, in the order found."""
        return [BindingRecord(self, binding_id) for binding_id in self.configs]


@dataclass(frozen=True, slots=True)
class BindingRecord:
    """One scene's binding record for a binding identity, read through the scene's records, so a write reaches it."""

    held: SceneRecords
    binding_id: BindingId

    @property
    def scene(self) -> bpy.types.Scene:
        """The scene holding the record."""
        return self.held.scene

    @property
    def scene_uid(self) -> int:
        """The scene's session_uid."""
        return self.held.uid

    @property
    def config(self) -> BindingConfig | RefusedRecord:
        """The configuration, or why it can't be read."""
        return self.held.configs[self.binding_id]


@dataclass(slots=True)
class DestinationRecords:
    """The records on a destination collection: its tag, and its manifest once read."""

    collection: bpy.types.Collection
    tag: DestinationTag | RefusedRecord | None  # None for a collection a binding record names that has no local tag
    manifest: Loaded[Manifest] | RefusedRecord | None | Unread = UNREAD


@dataclass(slots=True)
class IndexRecords:
    """The record on a Text holding a binding index: the index."""

    text: bpy.types.Text
    index: BindingIndex | RefusedRecord


@dataclass(slots=True)
class State:
    """The bindings' state, built from the records (the module docstring says how it's kept)."""

    scene_uids: tuple[int, ...]  # the session_uids of every scene it was built from, in order: compared at each use
    # The records, each held once, by the datablock holding them, in the order found.
    scenes: dict[int, SceneRecords]  # by session_uid: every local scene with binding records
    # By session_uid: every local tagged collection, then every other collection a record names.
    destinations: dict[int, DestinationRecords]
    indexes: list[IndexRecords]  # every local Text with a binding index; a file normally has one
    # Computed from the records.
    identities: dict[BindingId, IdentityCandidates]  # every identity with a record or a tag, records' first
    ownership: OwnershipIndex | None = None  # built when first asked for

    @property
    def tagged(self) -> frozenset[int]:
        """The session_uids of the local tagged collections (refresh_if_tags_changed)."""
        return frozenset(uid for uid, d in self.destinations.items() if d.tag is not None)

    def add_binding(self, scene: bpy.types.Scene, created: CreatedBinding) -> None:
        """Hold a binding just made on scene: the records create stored, and its identity's decision."""
        binding_id, destination = created.binding_id, created.config.destination
        assert destination is not None
        uid = scene.session_uid
        held = self.scenes.setdefault(uid, SceneRecords(scene, uid))
        held.configs[binding_id] = created.config
        self.destinations[destination.session_uid] = DestinationRecords(destination, created.tag, None)
        self.indexes = [IndexRecords(*created.index)]
        self.identities[binding_id] = copy_detection.identity(self, binding_id, [BindingRecord(held, binding_id)])

    def replace_index(self, binding_id: BindingId, written: WrittenIndex) -> None:
        """Hold the binding index a write stored with binding_id's entry, and decide that identity again.

        A write to the index refuses a file with more than one, so the file now has only this one.
        """
        self.indexes = [IndexRecords(*written)]
        identity = self.identities[binding_id]
        self.identities[binding_id] = copy_detection.identity(self, binding_id, identity.records)


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
    """A number that changes whenever the state is dropped or rebuilt.

    Runtime state kept beside the bindings, such as their stages (CurrentStages), compares it to tell when the bindings
    may have changed: after a load, undo, or redo, or when scenes are added or removed.
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
    if _state is None or _state.scene_uids != scenes:
        _state = _read_state(scenes)
        _rebuilds += 1
    return _state


def valid(binding_id: BindingId, record: BindingRecord) -> bool:
    """Whether the record's scene still exists and holds its configuration, and its destination still exists.

    Removing a destination clears the configuration's pointer to it.
    """
    destination = None if isinstance(record.config, RefusedRecord) else record.config.destination
    return (
        alive(record.scene)
        and records.has(record.scene, binding_records.config_key(binding_id))
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


def _read_state(scenes: tuple[int, ...]) -> State:
    """Read every binding record, tag, and binding index, and decide every identity."""
    held: dict[int, SceneRecords] = {}
    for scene, binding_id, result in binding_records.read_configs():
        uid = scene.session_uid
        configs = held.setdefault(uid, SceneRecords(scene, uid)).configs
        configs[binding_id] = result if isinstance(result, RefusedRecord) else result.record
    destinations = {
        collection.session_uid: DestinationRecords(collection, tag.record if isinstance(tag, Loaded) else tag)
        for collection, tag in binding_records.read_tags()
    }
    # A removed destination is left out, and checking a record naming it rebuilds the state.
    for scene_records in held.values():
        for config in scene_records.configs.values():
            if isinstance(config, BindingConfig) and (destination := config.destination) is not None:
                if alive(destination) and destination.session_uid not in destinations:
                    destinations[destination.session_uid] = DestinationRecords(destination, None)
    indexes = []
    for text in binding_records.index_texts():
        index = records.read(text, binding_records.INDEX_KEY, binding_records.INDEX)
        assert index is not None  # index_texts found the record
        indexes.append(IndexRecords(text, index.record if isinstance(index, Loaded) else index))
    current = State(scenes, held, destinations, indexes, {})
    current.identities = copy_detection.identities(current)
    return current
