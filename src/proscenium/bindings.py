"""Binding records: configuration, the destination's tag, and the binding index (lifecycle.md#binding-state).

A binding's configuration is a record on its target scene, under binding.<identifier>. Its
destination collection carries a tag naming the binding and pointing back at the scene, so the
scene's record and its destination refer to each other (source-access.md#canonical-candidate).

The binding index maps each binding's identifier to its destination. It is a record on its own
Text, not on any scene or collection, so duplicating or appending a binding never copies it. The
Text has a fake user, so Blender keeps it although nothing uses it.

The extension finds the index by looking for the Text that holds the index record, not by the
Text's name, which users can change. The name it gives the Text, .proscenium, starts with a dot so
Blender's datablock search menus leave it out unless the user turns on showing hidden data-blocks.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import bpy
from pxr import Usd

from . import records
from .core.source_access import SourceKind
from .records import RecordRefused, Refused, Schema

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .records import Loaded

CONFIG_PREFIX = "binding."
TAG_KEY = "destination"
INDEX_KEY = "index"
INDEX_NAME = ".proscenium"


class PayloadPolicy(StrEnum):
    """A binding's payload policy, as its configuration stores it."""

    LOAD_ALL = "load_all"
    LOAD_NONE = "load_none"

    @property
    def load_set(self) -> Usd.Stage.InitialLoadSet:
        return Usd.Stage.LoadAll if self is PayloadPolicy.LOAD_ALL else Usd.Stage.LoadNone

    @classmethod
    def of(cls, load_set: Usd.Stage.InitialLoadSet) -> PayloadPolicy:
        return cls.LOAD_ALL if load_set == Usd.Stage.LoadAll else cls.LOAD_NONE


@dataclass(frozen=True, slots=True)
class BindingConfig:
    """A binding's configuration: its source, its destination, and its requested settings."""

    source: SourceKind
    path: str | None  # a file source's root-layer path, as given: a "//" path is relative to the .blend
    key: str | None  # an attached source's source key
    root_layer_identifier: str | None  # of the stage last attached; informative only
    destination: bpy.types.Collection | None  # None once the destination is removed
    payload_policy: PayloadPolicy

    def __post_init__(self) -> None:
        # A record stores the enums' values as plain strings. One that isn't a member raises ValueError.
        object.__setattr__(self, "source", SourceKind(self.source))
        object.__setattr__(self, "payload_policy", PayloadPolicy(self.payload_policy))
        if self.source is SourceKind.FILE:
            if type(self.path) is not str or self.key is not None or self.root_layer_identifier is not None:
                raise ValueError("a file source has a path, and no key or root-layer identifier")
        else:
            if self.path is not None or type(self.key) is not str or not self.key:
                raise ValueError("an attached source has a key, and no path")
            if not isinstance(self.root_layer_identifier, str | None):
                raise TypeError("the root-layer identifier is not a string")
        if not isinstance(self.destination, bpy.types.Collection | None):
            raise TypeError("the destination is not a collection")


@dataclass(frozen=True, slots=True)
class DestinationTag:
    """On a destination collection: the binding it belongs to, and that binding's target scene."""

    binding_id: str
    scene: bpy.types.Scene

    def __post_init__(self) -> None:
        if type(self.binding_id) is not str or not isinstance(self.scene, bpy.types.Scene):
            raise TypeError("a destination tag names a binding and points at a scene")


@dataclass(frozen=True)
class BindingIndex:
    destinations: dict[str, bpy.types.Collection | None]  # binding identifier -> its destination

    def __post_init__(self) -> None:
        if not all(isinstance(d, bpy.types.Collection | None) for d in self.destinations.values()):
            raise TypeError("an index entry names something other than a collection")


CONFIG = Schema("binding", version=1, record=BindingConfig)
TAG = Schema("destination tag", version=1, record=DestinationTag)
INDEX = Schema("binding index", version=1, record=BindingIndex)


def new_identifier() -> str:
    return uuid.uuid4().hex


def config_key(binding_id: str) -> str:
    return CONFIG_PREFIX + binding_id


def create(scene: bpy.types.Scene, config: BindingConfig, name: str) -> tuple[str, BindingConfig]:
    """Make a binding on scene: its destination, linked under the scene's collection, and its records.

    Raises RecordRefused, changing nothing, if the binding index can't be read; ValueError if the
    file has more than one.
    """
    text, index = _index()  # first, so a failure changes nothing
    binding_id = new_identifier()
    destination = bpy.data.collections.new(name)
    scene.collection.children.link(destination)
    config = dataclasses.replace(config, destination=destination)
    records.write(scene, config_key(binding_id), CONFIG, config)
    records.write(destination, TAG_KEY, TAG, DestinationTag(binding_id, scene))
    if text is None:
        text = bpy.data.texts.new(INDEX_NAME)
        text.use_fake_user = True
    records.write(text, INDEX_KEY, INDEX, BindingIndex(index.destinations | {binding_id: destination}))
    return binding_id, config


def find(binding_id: str) -> tuple[bpy.types.Scene, Loaded[BindingConfig] | Refused] | None:
    """The scene holding binding_id's configuration, and the configuration or why it can't be read.

    Copies sharing an identity are detected and repaired separately; this returns the first scene.
    """
    key = config_key(binding_id)
    for scene in bpy.data.scenes:
        if (result := records.read(scene, key, CONFIG)) is not None:
            return scene, result
    return None


def update(scene: bpy.types.Scene, binding_id: str, config: BindingConfig) -> None:
    """Store a binding's changed configuration. Raises RecordRefused over one that can't be read."""
    records.write(scene, config_key(binding_id), CONFIG, config)


def scene_bindings(scene: bpy.types.Scene) -> list[str]:
    """The identifiers of the bindings whose configuration is on scene."""
    return [key.removeprefix(CONFIG_PREFIX) for key in records.keys(scene) if key.startswith(CONFIG_PREFIX)]


def all_bindings() -> Iterator[tuple[bpy.types.Scene, str, Loaded[BindingConfig] | Refused]]:
    """Every binding in the file: its scene, identifier, and configuration or why it can't be read."""
    for scene in bpy.data.scenes:
        for binding_id in scene_bindings(scene):
            result = records.read(scene, config_key(binding_id), CONFIG)
            assert result is not None
            yield scene, binding_id, result


def index_texts() -> list[bpy.types.Text]:
    """Every Text holding a binding index record, readable or not, found by the record rather than the Text's name.

    A file normally has one: the index maps each binding's identifier to its destination, and is
    how the canonical-candidate rule tells an original binding from its copies. A second one comes
    from appending the index Text from another .blend. With two, the rule can't decide, so
    every binding sharing an identity is disabled pending repair (source-access.md#canonical-candidate).
    """
    return [text for text in bpy.data.texts if records.stored(text, INDEX_KEY) is not None]


def _index() -> tuple[bpy.types.Text | None, BindingIndex]:
    """The file's binding index, and the Text holding it, for a change to the index.

    A file without one has an empty index and no Text yet; the caller creates the Text when it
    writes. Raises ValueError if the file has more than one index, and RecordRefused if the index
    can't be read: writing over either would destroy evidence the canonical-candidate rule reads.
    """
    texts = index_texts()
    if len(texts) > 1:
        raise ValueError(f"This file has {len(texts)} binding indexes")
    if not texts:
        return None, BindingIndex({})
    result = records.read(texts[0], INDEX_KEY, INDEX)
    if isinstance(result, Refused):
        raise RecordRefused(result)
    assert result is not None  # index_texts found the record
    return texts[0], result.record
