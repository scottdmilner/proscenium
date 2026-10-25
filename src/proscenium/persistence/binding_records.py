"""Binding records: configuration, the destination's tag, and the binding index (lifecycle.md#binding-state).

- Configuration: a record on the binding's target scene, under binding.<identifier>.
- Destination tag: a record on the destination collection naming the binding and pointing back at the scene, so the
  configuration and its destination refer to each other (source-access.md#canonical-candidate).
- Binding index: each binding's identifier to its destination, a record on its own Text, so duplicating or appending
  a binding never copies it. The Text has a fake user, so Blender keeps it though nothing uses it. It is found by its
  record, not by its name, which users can change; the name it is given, .proscenium, starts with a dot so Blender's
  datablock search menus leave it out unless the user shows hidden data-blocks.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

import bpy

from ..core.binding_ids import BindingId
from ..core.requested_settings import RequestedSettings
from ..core.source_access import SourceKind
from . import records
from .records import RefusedRecord, RefusedRecordError, Schema

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .records import Loaded

CONFIG_PREFIX = "binding."
TAG_KEY = "destination"
INDEX_KEY = "index"
INDEX_NAME = ".proscenium"


@dataclass(frozen=True, slots=True)
class BindingConfig:
    """A binding's configuration: its source, its destination, and its requested settings."""

    source_kind: SourceKind
    path: str | None  # a file source's root-layer path, as given: a "//" path is relative to the .blend
    source_key: str | None  # an attached source's source key
    root_layer_identifier: str | None  # of the stage last attached; informative only
    destination: bpy.types.Collection | None  # None once the destination is removed
    settings: RequestedSettings

    @classmethod
    def file(
        cls, path: str, settings: RequestedSettings, *, destination: bpy.types.Collection | None = None
    ) -> BindingConfig:
        """A file source's configuration: its root-layer path, as given."""
        return cls(SourceKind.FILE, path, None, None, destination, settings)

    @classmethod
    def attached(
        cls,
        key: str,
        settings: RequestedSettings,
        *,
        root_layer_identifier: str | None = None,
        destination: bpy.types.Collection | None = None,
    ) -> BindingConfig:
        """An attached source's configuration: its source key, and the root-layer identifier last attached."""
        return cls(SourceKind.ATTACHED, None, key, root_layer_identifier, destination, settings)

    def __post_init__(self) -> None:
        # A record stores the enum's value as a plain string, and the settings as a group of plain values. One that
        # isn't a member raises ValueError.
        object.__setattr__(self, "source_kind", SourceKind(self.source_kind))
        if isinstance(self.settings, Mapping):
            object.__setattr__(self, "settings", RequestedSettings(**self.settings))
        if not isinstance(self.settings, RequestedSettings):
            raise TypeError("the requested settings are not a group")
        if self.source_kind is SourceKind.FILE:
            if type(self.path) is not str or self.source_key is not None or self.root_layer_identifier is not None:
                raise ValueError("a file source has a path, and no key or root-layer identifier")
        else:
            if self.path is not None or type(self.source_key) is not str or not self.source_key:
                raise ValueError("an attached source has a key, and no path")
            if not isinstance(self.root_layer_identifier, str | None):
                raise TypeError("the root-layer identifier is not a string")
        if not isinstance(self.destination, bpy.types.Collection | None):
            raise TypeError("the destination is not a collection")


@dataclass(frozen=True, slots=True)
class DestinationTag:
    """On a destination collection: the binding it belongs to, and that binding's target scene."""

    binding_id: BindingId
    scene: bpy.types.Scene

    def __post_init__(self) -> None:
        if type(self.binding_id) is not str or not isinstance(self.scene, bpy.types.Scene):
            raise TypeError("a destination tag names a binding and points at a scene")


@dataclass(frozen=True)
class BindingIndex:
    """The file's binding index: each binding's destination, which the canonical-candidate rule reads."""

    destinations: dict[BindingId, bpy.types.Collection | None]  # each binding's destination

    def __post_init__(self) -> None:
        if not all(isinstance(d, bpy.types.Collection | None) for d in self.destinations.values()):
            raise TypeError("an index entry names something other than a collection")


CONFIG = Schema("binding", version=1, record_type=BindingConfig)
TAG = Schema("destination tag", version=1, record_type=DestinationTag)
INDEX = Schema("binding index", version=1, record_type=BindingIndex)


class WrittenIndex(NamedTuple):
    """The binding index as a write stored it, and the Text holding it."""

    text: bpy.types.Text
    index: BindingIndex


class CreatedBinding(NamedTuple):
    """What create stored: the new binding's identifier and its records."""

    binding_id: BindingId
    config: BindingConfig  # naming the new destination
    tag: DestinationTag  # on that destination
    index: WrittenIndex  # with the binding's entry


def new_identifier() -> BindingId:
    """A new, random binding identifier."""
    return BindingId(uuid.uuid4().hex)


def config_key(binding_id: BindingId) -> str:
    """The ID-property key of a binding's configuration record on its scene."""
    return CONFIG_PREFIX + binding_id


def create(scene: bpy.types.Scene, config: BindingConfig, name: str) -> CreatedBinding:
    """Make a binding on scene: its destination, linked under the scene's collection, and its records.

    Raises RefusedRecordError, changing nothing, if the binding index can't be read; ValueError if the
    file has more than one.
    """
    text, index = _index()  # first, so a failure changes nothing
    binding_id = new_identifier()
    destination = bpy.data.collections.new(name)
    scene.collection.children.link(destination)
    config = dataclasses.replace(config, destination=destination)
    tag = DestinationTag(binding_id, scene)
    records.write(scene, config_key(binding_id), CONFIG, config)
    records.write(destination, TAG_KEY, TAG, tag)
    return CreatedBinding(binding_id, config, tag, _write_entry(text, index, binding_id, destination))


def write_config(scene: bpy.types.Scene, binding_id: BindingId, config: BindingConfig) -> None:
    """Store a binding's changed configuration. Raises RefusedRecordError over one that can't be read."""
    records.write(scene, config_key(binding_id), CONFIG, config)


def scene_bindings(scene: bpy.types.Scene) -> list[BindingId]:
    """The identifiers of the bindings whose configuration is on scene."""
    return [BindingId(key.removeprefix(CONFIG_PREFIX)) for key in records.keys(scene) if key.startswith(CONFIG_PREFIX)]


def read_configs() -> Iterator[tuple[bpy.types.Scene, BindingId, Loaded[BindingConfig] | RefusedRecord]]:
    """Every binding record in the file: its scene, identifier, and configuration or why it can't be read.

    Linked scenes are left out: library data is read-only here, and its bindings belong to its library
    (source-access.md#canonical-candidate).
    """
    for scene in bpy.data.scenes:
        if scene.library is not None:
            continue
        for binding_id in scene_bindings(scene):
            result = records.read(scene, config_key(binding_id), CONFIG)
            assert result is not None
            yield scene, binding_id, result


def index_texts() -> list[bpy.types.Text]:
    """Every local Text holding a binding index record, readable or not.

    A file normally has one. A second comes from appending the index Text from another .blend; the
    canonical-candidate rule can't decide on an identity both name, so its bindings are disabled pending repair
    (source-access.md#canonical-candidate). A linked Text's index belongs to its library.
    """
    texts = bpy.data.texts
    return [text for text in texts if text.library is None and records.stored(text, INDEX_KEY) is not None]


def read_tags() -> Iterator[tuple[bpy.types.Collection, Loaded[DestinationTag] | RefusedRecord]]:
    """Every local collection with a destination tag, and the tag or why it can't be read.

    These are each binding's destination, and every copy of one (source-access.md#copied-bindings).
    """
    for collection in bpy.data.collections:
        if _tagged(collection):
            tag = records.read(collection, TAG_KEY, TAG)
            assert tag is not None  # _tagged found the record
            yield collection, tag


def tagged_uids() -> frozenset[int]:
    """The session_uids of the collections read_tags gives, without reading their tags."""
    return frozenset(collection.session_uid for collection in bpy.data.collections if _tagged(collection))


def restore_entry(binding_id: BindingId, destination: bpy.types.Collection) -> WrittenIndex | None:
    """Add a binding's missing index entry, making the index's Text if the file has none; the index written, if any.

    Raises as create does, writing nothing; an entry the index has, even one naming no destination, is kept.
    """
    text, index = _index()
    if binding_id in index.destinations:
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
    result = records.read(texts[0], INDEX_KEY, INDEX)
    if isinstance(result, RefusedRecord):
        raise RefusedRecordError(result)
    assert result is not None  # index_texts found the record
    return texts[0], result.record


def _write_entry(
    text: bpy.types.Text | None, index: BindingIndex, binding_id: BindingId, destination: bpy.types.Collection
) -> WrittenIndex:
    """Write the index with binding_id's entry naming destination, on a new Text if there is none."""
    if text is None:
        text = bpy.data.texts.new(INDEX_NAME)
        text.use_fake_user = True
    written = BindingIndex(index.destinations | {binding_id: destination})
    records.write(text, INDEX_KEY, INDEX, written)
    return WrittenIndex(text, written)


def _tagged(collection: bpy.types.Collection) -> bool:
    return collection.library is None and records.has(collection, TAG_KEY)
