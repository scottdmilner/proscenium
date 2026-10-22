"""F-OWNERSHIP-AMBIGUITY's routes, run in Blender, and the file's records by name (fixtures.copies).

Each route acts on a binding "Shot" on the scene "Scene", whose destination holds the managed object
"Managed" with a manifest naming it. Routes that bring data from another .blend save a copy of the open
file beside it first, so the other file holds the same binding.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy

from proscenium.persistence import binding_records, manifests, records
from proscenium.persistence.manifests import Manifest
from proscenium.persistence.records import Loaded

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def run(route: str, tmp_path: Path) -> None:
    ROUTES[route](tmp_path)


def records_by_name() -> dict[tuple[str, str], Any]:
    """Every scene's, collection's, object's, and text's records, with ID pointers as names.

    Also each collection's objects: what detection must leave as it was.
    """
    found: dict[tuple[str, str], Any] = {}
    for kind, ids in (("scene", bpy.data.scenes), ("collection", bpy.data.collections), ("text", bpy.data.texts)):
        for id_ in ids:
            found[kind, id_.name] = {key: _named(records.stored(id_, key)) for key in records.keys(id_)}
    for obj in bpy.data.objects:
        found["object", obj.name] = {key: _named(records.stored(obj, key)) for key in records.keys(obj)}
    for collection in bpy.data.collections:
        found["objects in", collection.name] = sorted(o.name for o in collection.objects)
    return found


def _named(value: object) -> object:
    if isinstance(value, bpy.types.ID):
        return f"{type(value).__name__}:{value.name}"
    if isinstance(value, dict):
        return {k: _named(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_named(v) for v in value]
    return value


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _shot() -> bpy.types.Collection:
    return bpy.data.collections["Shot"]


def _index_text() -> bpy.types.Text:
    [text] = binding_records.index_texts()
    return text


def _write_entries(change: Callable[[dict[str, bpy.types.Collection | None]], None]) -> None:
    index = records.read(_index_text(), binding_records.INDEX_KEY, binding_records.INDEX)
    assert isinstance(index, Loaded)
    destinations = dict(index.record.destinations)
    change(destinations)
    records.write(
        _index_text(), binding_records.INDEX_KEY, binding_records.INDEX, binding_records.BindingIndex(destinations)
    )


def _copy_collection(_: Path) -> bpy.types.Collection:
    """A script copies the destination and links the copy: its records and objects are the original's."""
    copy = _shot().copy()
    _scene().collection.children.link(copy)
    return copy


def _deep_copy_collection(tmp_path: Path) -> None:
    """Outliner > Duplicate Collection's state, inferred from the full-copy scene (D1).

    The objects copied, and the copy's manifest naming the copies, its tag the original's.
    """
    copy = _copy_collection(tmp_path)
    copies = {}
    for obj in list(copy.objects):
        copies[obj] = obj.copy()
        copy.objects.unlink(obj)
        copy.objects.link(copies[obj])
    manifest = manifests.read_manifest(copy)
    assert isinstance(manifest, Loaded)
    entries = {
        key: type(entry)(copies.get(entry.datablock, entry.datablock), entry.covers, entry.role, entry.uses)
        for key, entry in manifest.record.entries.items()
    }
    manifests.write_manifest(copy, Manifest(entries))


def _copy_scene(kind: str) -> Callable[[Path], None]:
    def copy_scene(_: Path) -> None:
        window = bpy.context.window
        assert window is not None
        window.scene = _scene()
        bpy.ops.scene.new(type=kind)  # ty: ignore[invalid-argument-type] - stubs type the enum as a literal union

    return copy_scene


def _other_file(tmp_path: Path) -> Path:
    other = tmp_path / "other.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(other), copy=True, check_existing=False)
    return other


def _load(tmp_path: Path, attr: str, name: str, *, link: bool) -> list[bpy.types.ID]:
    other = _other_file(tmp_path)
    with bpy.data.libraries.load(str(other), link=link) as (_src, dst):  # ty: ignore[invalid-context-manager] - stubs
        setattr(dst, attr, [name])
    return getattr(dst, attr)


def _append(tmp_path: Path) -> None:
    """Append the destination from a copy of the file, linking it under the scene: its tag brings its scene."""
    for collection in _load(tmp_path, "collections", "Shot", link=False):
        assert isinstance(collection, bpy.types.Collection)
        _scene().collection.children.link(collection)


def _link(tmp_path: Path) -> None:
    for collection in _load(tmp_path, "collections", "Shot", link=True):
        assert isinstance(collection, bpy.types.Collection)
        _scene().collection.children.link(collection)


def _append_index(tmp_path: Path) -> None:
    """A user appends the other file's index Text; its entry's pointer brings the destination, and its scene."""
    _load(tmp_path, "texts", binding_records.INDEX_NAME, link=False)


def _copy_records(_: Path) -> None:
    """A script copies the binding's records, by assignment, onto a new scene and collection."""
    scene = bpy.data.scenes.new("Scripted")
    destination = bpy.data.collections.new("ScriptedDest")
    scene.collection.children.link(destination)
    scene[records.NAMESPACE] = _scene()[records.NAMESPACE]
    destination[records.NAMESPACE] = _shot()[records.NAMESPACE]


def _lose_index(_: Path) -> None:
    bpy.data.texts.remove(_index_text())


def _remove_tag(_: Path) -> None:
    del _shot()[records.NAMESPACE][binding_records.TAG_KEY]


def _clear_entries(_: Path) -> None:
    _write_entries(lambda destinations: destinations.update(dict.fromkeys(destinations)))


def _disagree(tmp_path: Path) -> None:
    copy = _copy_collection(tmp_path)
    _write_entries(lambda destinations: destinations.update(dict.fromkeys(destinations, copy)))


def _unreadable_index(_: Path) -> None:
    _index_text()[records.NAMESPACE][binding_records.INDEX_KEY][records.VERSION_KEY] = 2  # a newer extension's


def _duplicate_object(_: Path) -> None:
    """Object > Duplicate (Shift+D) on the managed object."""
    obj = bpy.data.objects["Managed"]
    view_layer = bpy.context.view_layer
    assert view_layer is not None
    obj.select_set(True)
    view_layer.objects.active = obj
    bpy.ops.object.duplicate()


def _then(*steps: Callable[[Path], object]) -> Callable[[Path], None]:
    def run_steps(tmp_path: Path) -> None:
        for step in steps:
            step(tmp_path)

    return run_steps


ROUTES: dict[str, Callable[[Path], object]] = {
    "collection-copy": _copy_collection,
    "deep-collection-copy": _deep_copy_collection,
    "full-copy-scene": _copy_scene("FULL_COPY"),
    "linked-copy-scene": _copy_scene("LINK_COPY"),
    "append": _append,
    "record-copy": _copy_records,
    "index-lost": _then(_lose_index, _copy_scene("FULL_COPY")),
    "index-lost-linked-copy": _then(_lose_index, _copy_scene("LINK_COPY")),
    "entry-cleared": _then(_clear_entries, _copy_scene("LINK_COPY")),
    "none-mutual": _then(_lose_index, _remove_tag, _copy_scene("LINK_COPY")),
    "index-disagrees": _disagree,
    "unreadable-index": _then(_unreadable_index, _copy_scene("FULL_COPY")),
    "two-indexes": _append_index,
    "linked-binding": _link,
    "duplicated-object": _duplicate_object,
}
