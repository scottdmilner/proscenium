"""Binding records: configuration, on the destination collection, and the binding index (lifecycle.md#binding-state).

- Configuration: a record on the binding's destination collection, under binding.<identifier>, pointing at its target
  scene. The destination is the binding: removing it, or the target scene, removes the binding
  (lifecycle.md#removed-destination). Its identifier is in the key, so a configuration that can't be read still names
  its binding.
- Binding index: each binding's identifier to its destination, a record on its own Text, so duplicating or appending
  a binding never copies it. The Text has a fake user, so Blender keeps it though nothing uses it. It is found by its
  record, not by its name, which users can change; the name it is given, .proscenium, starts with a dot so Blender's
  datablock search menus leave it out unless the user shows hidden data-blocks.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

import bpy

from ..source_access import binding_settings, identifiers
from . import records
from .records import RefusedRecord, RefusedRecordError, Schema

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .records import LoadedRecord

CONFIG_PREFIX = "binding."
INDEX_KEY = "index"
INDEX_NAME = ".proscenium"


@dataclass(frozen=True, slots=True)
class BindingConfig:
    """A binding's configuration: its target scene, last attached root identifier, and requested settings."""

    scene: bpy.types.Scene | None  # its target scene; None once the scene is removed, which removes the binding
    settings: binding_settings.RequestedSettings
    root_layer_identifier: str | None = None  # of the stage last attached; informative only

    def __post_init__(self) -> None:
        if isinstance(self.settings, Mapping):
            object.__setattr__(self, "settings", binding_settings.RequestedSettings(**self.settings))
        if not isinstance(self.settings, binding_settings.RequestedSettings):
            raise TypeError("the requested settings are not a group")
        if not isinstance(self.root_layer_identifier, str | None):
            raise TypeError("the root-layer identifier is not a string")
        if not isinstance(self.scene, bpy.types.Scene | None):
            raise TypeError("the target scene is not a scene")


@dataclass(frozen=True)
class BindingIndex:
    """The file's binding index: each binding's destination, which the canonical-candidate rule reads."""

    destinations: dict[identifiers.BindingId, bpy.types.Collection | None]  # each binding's destination

    def __post_init__(self) -> None:
        if not all(isinstance(d, bpy.types.Collection | None) for d in self.destinations.values()):
            raise TypeError("an index entry names something other than a collection")


CONFIG = Schema("binding", version=1, record_type=BindingConfig)
INDEX = Schema("binding index", version=1, record_type=BindingIndex)


class WrittenIndex(NamedTuple):
    """The binding index as a write stored it, and the Text holding it."""

    text: bpy.types.Text
    index: BindingIndex


class CreatedBinding(NamedTuple):
    """What create stored: the new binding's identifier, destination, and records."""

    binding_id: identifiers.BindingId
    destination: bpy.types.Collection
    config: BindingConfig  # on the destination
    index: WrittenIndex  # with the binding's entry


def new_identifier() -> identifiers.BindingId:
    """A new, random binding identifier."""
    return identifiers.BindingId(uuid.uuid4().hex)


def config_key(binding_id: identifiers.BindingId) -> str:
    """The ID-property key of a binding's configuration record on its destination."""
    return CONFIG_PREFIX + binding_id


def create_binding(scene: bpy.types.Scene, settings: binding_settings.RequestedSettings, name: str) -> CreatedBinding:
    """Make a binding on scene: its destination, linked under the scene's collection, and its records.

    Raises RefusedRecordError, changing nothing, if the binding index can't be read; ValueError if the
    file has more than one.
    """
    text, index = _index()  # first, so a failure changes nothing
    binding_id = new_identifier()
    destination = bpy.data.collections.new(name)
    scene.collection.children.link(destination)
    config = BindingConfig(scene, settings)
    records.write(destination, config_key(binding_id), CONFIG, config)
    return CreatedBinding(binding_id, destination, config, _write_entry(text, index, binding_id, destination))


def has_config(destination: bpy.types.Collection, binding_id: identifiers.BindingId) -> bool:
    """Whether destination stores a configuration record for binding_id, without reading it."""
    return records.has(destination, config_key(binding_id))


def read_index(text: bpy.types.Text) -> LoadedRecord[BindingIndex] | RefusedRecord | None:
    """The binding index text holds, why it can't be read, or None if it holds none."""
    return records.read(text, INDEX_KEY, INDEX)


def write_config(destination: bpy.types.Collection, binding_id: identifiers.BindingId, config: BindingConfig) -> None:
    """Store a binding's changed configuration. Raises RefusedRecordError over one that can't be read."""
    records.write(destination, config_key(binding_id), CONFIG, config)


def binding_ids(collection: bpy.types.Collection) -> list[identifiers.BindingId]:
    """The identifiers of the bindings whose configuration is on collection; normally one, or none."""
    return [
        identifiers.BindingId(key.removeprefix(CONFIG_PREFIX))
        for key in records.keys(collection)
        if key.startswith(CONFIG_PREFIX)
    ]


def read_configs() -> Iterator[
    tuple[bpy.types.Collection, identifiers.BindingId, LoadedRecord[BindingConfig] | RefusedRecord]
]:
    """Every binding record in the file: its collection, identifier, and configuration or why it can't be read.

    Linked collections are left out: library data is read-only here, and its bindings belong to its library
    (source-access.md#canonical-candidate).
    """
    for collection in bpy.data.collections:
        if collection.library is not None:
            continue
        for binding_id in binding_ids(collection):
            result = records.read(collection, config_key(binding_id), CONFIG)
            assert result is not None
            yield collection, binding_id, result


def destination_collection_uids() -> frozenset[int]:
    """The session_uids of the collections read_configs reads, without reading their records."""
    return frozenset(c.session_uid for c in bpy.data.collections if c.library is None and binding_ids(c))


def index_texts() -> list[bpy.types.Text]:
    """Every local Text holding a binding index record, readable or not.

    A file normally has one. A second comes from appending the index Text from another .blend; the
    canonical-candidate rule can't decide on an identity both name, so its bindings are disabled pending repair
    (source-access.md#canonical-candidate). A linked Text's index belongs to its library.
    """
    texts = bpy.data.texts
    return [text for text in texts if text.library is None and records.stored(text, INDEX_KEY) is not None]


def restore_index_entry(binding_id: identifiers.BindingId, destination: bpy.types.Collection) -> WrittenIndex | None:
    """Write a binding's index entry where it has none or one naming no collection; the index written, if any.

    Makes the index's Text if the file has none.

    Raises as create_binding does, writing nothing; an entry naming a collection is kept, and one naming none replaced.
    """
    text, index = _index()
    if index.destinations.get(binding_id) is not None:
        return None
    return _write_entry(text, index, binding_id, destination)


def _index() -> tuple[bpy.types.Text | None, BindingIndex]:
    """The file's binding index, and the Text holding it, for a change to the index.

    A file without one has an empty index and no Text yet; the caller creates the Text when it
    writes. Raises ValueError if the file has more than one index, and RefusedRecordError if the index
    can't be read: writing over either would destroy evidence the canonical-candidate rule reads.
    """
    texts = index_texts()
    if len(texts) > 1:
        raise ValueError(f"This file has {len(texts)} binding indexes")
    if not texts:
        return None, BindingIndex({})
    result = read_index(texts[0])
    if isinstance(result, RefusedRecord):
        raise RefusedRecordError(result)
    assert result is not None  # index_texts found the record
    return texts[0], result.record


def _write_entry(
    text: bpy.types.Text | None,
    index: BindingIndex,
    binding_id: identifiers.BindingId,
    destination: bpy.types.Collection,
) -> WrittenIndex:
    """Write the index with binding_id's entry naming destination, on a new Text if there is none."""
    if text is None:
        text = bpy.data.texts.new(INDEX_NAME)
        text.use_fake_user = True
    written = BindingIndex(index.destinations | {binding_id: destination})
    records.write(text, INDEX_KEY, INDEX, written)
    return WrittenIndex(text, written)
