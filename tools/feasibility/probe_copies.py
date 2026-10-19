"""Probe 10 (M3): what Blender's copy routes do to a binding's ID properties and ID pointers.

The base file holds one binding, tagged with ID-property records on three datablocks:
- the scene: binding identity and an ID pointer to the destination collection;
- the destination collection: binding identity and an ID pointer back to the scene;
- the managed object in it: binding identity and an ID pointer to the destination.

It also holds a file-level index naming the binding's destination by ID pointer, on two
candidate hosts outside the binding's datablocks: a Text and an unlinked collection, each with
a fake user. Nothing points at the index.

Each route starts from the base file, copies the binding the way a user or script would, and
records every tagged datablock and index host, with their pointers, before and after a save and
reopen. Where the records live is M3's choice, so the facts cover every tagged datablock rather
than one layout. The checks hold the outcomes the canonical-candidate rule (D2) is built on.
"""

from __future__ import annotations

import shutil
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from _common import Probe

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import bpy

KEY = "proscenium_probe"
INDEX = "proscenium_probe_index"
INDEX_HOST = "ProsceniumIndex"
BINDING = "B1"


@dataclass(frozen=True)
class Route:
    """A copy route and the outcome D2 builds on; None where nothing is expected."""

    run: Callable[[], object]  # its return value is ignored
    tagged: dict[str, int] | None = None  # tagged datablocks by kind after the route
    pairs: int | None = None  # scene/collection pairs whose records point at each other
    index_unchanged: bool = True  # whether the index still names only the original before the save


def run() -> dict[str, Any]:
    p = Probe("copies")
    base = p.tmp / "base.blend"
    other = p.tmp / "other.blend"
    _write_base(base)
    shutil.copy(base, other)  # another file holding the same binding, to append or link from
    both = {"scene": 2, "collection": 2, "object": 2}
    routes = {
        "outliner duplicate collection": Route(_outliner_duplicate),
        "Collection.copy()": Route(_copy_collection, {"scene": 1, "collection": 2, "object": 1}, 1),
        "full-copy scene": Route(lambda: _new_scene("FULL_COPY"), both, 2),
        "linked-copy scene": Route(lambda: _new_scene("LINK_COPY"), {"scene": 2, "collection": 1, "object": 1}, 1),
        "append collection (wm.append)": Route(lambda: _append_operator(other, "Collection", "Dest"), both, 2),
        "append collection (libraries.load)": Route(lambda: _load(other, "collections", link=False), both, 2),
        "append scene (wm.append)": Route(lambda: _append_operator(other, "Scene", "Scene"), both, 2),
        "link collection (libraries.load)": Route(lambda: _load(other, "collections", link=True), both, 2),
        "duplicate managed object": Route(_duplicate_object, {"scene": 1, "collection": 1, "object": 2}, 1),
        "record assigned through Python": Route(_assign_record, {"scene": 2, "collection": 2, "object": 1}, 1),
        "append the index Text": Route(lambda: _append_index(other, "texts"), both, 2, index_unchanged=False),
        "append the index collection": Route(
            lambda: _append_index(other, "collections"), both, 2, index_unchanged=False
        ),
    }
    original = p.fact("base", lambda: _open_and_snapshot(base))
    for name, route in routes.items():
        outcome = p.fact(name, lambda r=route: _route(base, p.tmp / "saved.blend", r.run))
        if outcome is None or "error" in outcome or original is None:
            continue
        _check_route(p, name, route, outcome, original)
    p.fact("record assignment copies the group", _assignment_is_copy)
    for link in (False, True):
        verb = "linked" if link else "appended"
        p.fact(
            f"{verb} with a collection whose record has no scene pointer",
            lambda as_link=link: _without_scene(p.tmp, as_link),
        )
    p.fact("appended index hosts", lambda: _appended_host_users(other))
    p.fact("users held by record pointers", _users)
    p.fact("destination removed with bpy.data.collections.remove", lambda: _removed_destination(p.tmp))
    p.fact("window manager records", lambda: _window_manager(p.tmp))
    return p.result()


def _check_route(p: Probe, name: str, route: Route, outcome: dict[str, Any], original: dict[str, Any]) -> None:
    if route.tagged is not None:
        p.check(f"{name}: tagged datablocks by kind", lambda: _kinds(outcome["tagged"]), route.tagged)
    if route.pairs is not None:
        p.check(f"{name}: scene/collection pairs pointing at each other", lambda: len(outcome["pairs"]), route.pairs)
    if route.index_unchanged:
        p.check(f"{name}: the index names only the original", lambda: outcome["indexes"] == original["indexes"])
    p.check(f"{name}: records survive save and reopen", lambda: outcome["reopened"]["tagged"] == outcome["tagged"])
    p.check(
        f"{name}: after reopening, the index names only the original",
        lambda: outcome["reopened"]["indexes"] == original["indexes"],
    )


def _write_base(path: Path) -> None:
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    _tag_binding(with_records=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(path))


def _tag_binding(*, with_records: bool) -> bpy.types.Collection:
    """The base binding in the current file; without records, the same datablocks untagged."""
    import bpy

    scene = bpy.data.scenes[0]
    scene.name = "Scene"
    dest = bpy.data.collections.new("Dest")
    scene.collection.children.link(dest)
    obj = bpy.data.objects.new("Managed", bpy.data.meshes.new("ManagedMesh"))
    dest.objects.link(obj)
    if with_records:
        scene[KEY] = {"binding_id": BINDING, "destination": dest}
        dest[KEY] = {"binding_id": BINDING, "scene": scene}
        obj[KEY] = {"binding_id": BINDING, "destination": dest}
        for host in (bpy.data.texts.new(INDEX_HOST), bpy.data.collections.new(INDEX_HOST)):
            host.use_fake_user = True
            host[INDEX] = {BINDING: dest}
    return dest


def _open_and_snapshot(path: Path) -> dict[str, Any]:
    import bpy

    bpy.ops.wm.open_mainfile(filepath=str(path))
    return _snapshot()


def _route(base: Path, saved: Path, route: Callable[[], object]) -> dict[str, Any]:
    import bpy

    bpy.ops.wm.open_mainfile(filepath=str(base))
    try:
        route()
    except Exception as exc:  # noqa: BLE001 - a route Blender refuses is itself a finding
        return {"error": f"{type(exc).__name__}: {str(exc).strip()}"}
    before = _snapshot()
    bpy.ops.wm.save_as_mainfile(filepath=str(saved))
    bpy.ops.wm.open_mainfile(filepath=str(saved))
    return {**before, "reopened": _snapshot()}


def _snapshot() -> dict[str, Any]:
    tagged = _tagged()
    return {
        "tagged": tagged,
        "pairs": _mutual(tagged),
        "object tags not naming their collection": _disagreeing_objects(),
        "indexes": _indexes(),
    }


def _tagged() -> dict[str, dict[str, Any]]:
    """Every datablock whose record has the binding identity, with the record's ID pointers by name."""
    import bpy

    out: dict[str, dict[str, Any]] = {}
    for kind, ids in (("scene", bpy.data.scenes), ("collection", bpy.data.collections), ("object", bpy.data.objects)):
        for id_ in ids:
            record = id_.get(KEY)
            if record is None or record.get("binding_id") != BINDING:
                continue
            refs = {k: _label(v) for k, v in record.items() if isinstance(v, bpy.types.ID)}
            out[_label(id_, kind)] = refs
    return out


def _kinds(tagged: dict[str, dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(label.split(":", 1)[0] for label in tagged))


def _mutual(tagged: dict[str, dict[str, Any]]) -> list[str]:
    """Scene/collection pairs whose records point at each other."""
    return sorted(
        f"{scene} <-> {refs['destination']}"
        for scene, refs in tagged.items()
        if scene.startswith("scene:") and tagged.get(refs.get("destination", ""), {}).get("scene") == scene
    )


def _disagreeing_objects() -> list[str]:
    """Tagged objects in a tagged collection whose tag names another collection."""
    import bpy

    out = []
    for collection in bpy.data.collections:
        if collection.get(KEY) is None:
            continue
        for obj in collection.objects:
            record = obj.get(KEY)
            if record is not None and record.get("destination") != collection:
                out.append(f"{_label(obj)} in {_label(collection)} names {_label(record['destination'])}")
    return sorted(out)


def _indexes() -> dict[str, dict[str, str | None]]:
    """Every index host, with the destination it names for each binding (None once the pointer is cleared)."""
    import bpy

    return {
        _label(host, kind): {binding: _label(dest) if dest else None for binding, dest in host[INDEX].items()}
        for kind, ids in (("text", bpy.data.texts), ("collection", bpy.data.collections))
        for host in ids
        if INDEX in host
    }


def _label(id_: bpy.types.ID, kind: str | None = None) -> str:
    kind = kind or type(id_).__name__.lower()
    library = f" [linked from {id_.library.name}]" if id_.library else ""
    return f"{kind}:{id_.name}{library}"


def _dest() -> bpy.types.Collection:
    import bpy

    return bpy.data.collections["Dest"]


def _outliner_duplicate() -> None:
    """Outliner > Duplicate Collection, with the destination as the active collection."""
    import bpy

    window = bpy.context.window
    assert window is not None and window.screen is not None
    area = next(a for a in window.screen.areas if a.type == "OUTLINER")
    region = next(r for r in area.regions if r.type == "WINDOW")
    view_layer = bpy.context.view_layer
    assert view_layer is not None
    view_layer.active_layer_collection = view_layer.layer_collection.children["Dest"]
    with bpy.context.temp_override(window=window, area=area, region=region):  # ty: ignore[invalid-context-manager] - stubs
        bpy.ops.outliner.select_all(action="SELECT")
        bpy.ops.outliner.collection_duplicate()


def _copy_collection() -> None:
    """A script copies the destination and links the copy, which would otherwise have no users."""
    import bpy

    bpy.data.scenes["Scene"].collection.children.link(_dest().copy())


def _new_scene(kind: str) -> None:
    import bpy

    window = bpy.context.window
    assert window is not None
    window.scene = bpy.data.scenes["Scene"]
    bpy.ops.scene.new(type=kind)  # ty: ignore[invalid-argument-type] - stubs type the enum as a literal union


def _append_operator(blend: Path, kind: str, name: str) -> None:
    import bpy

    directory = f"{blend}/{kind}/"
    bpy.ops.wm.append(filepath=directory + name, directory=directory, filename=name)


def _load(blend: Path, attr: str, *, link: bool) -> list[bpy.types.ID]:
    """Append or link the file's "Dest", linking each loaded collection into the scene."""
    import bpy

    with bpy.data.libraries.load(str(blend), link=link) as (_src, dst):  # ty: ignore[invalid-context-manager] - stubs
        setattr(dst, attr, ["Dest"])
    loaded = getattr(dst, attr)
    scene = bpy.data.scenes["Scene"]
    for collection in loaded:
        scene.collection.children.link(collection)
    return loaded


def _duplicate_object() -> None:
    """Object > Duplicate (Shift+D) on the managed object."""
    import bpy

    obj = bpy.data.objects["Managed"]
    view_layer = bpy.context.view_layer
    assert view_layer is not None
    obj.select_set(True)
    view_layer.objects.active = obj
    bpy.ops.object.duplicate()


def _assign_record() -> None:
    """A script copies the binding's records onto new datablocks by assignment."""
    import bpy

    scene = bpy.data.scenes.new("Scripted")
    dest = bpy.data.collections.new("ScriptedDest")
    scene.collection.children.link(dest)
    scene[KEY] = bpy.data.scenes["Scene"][KEY]
    dest[KEY] = _dest()[KEY]


def _append_index(blend: Path, attr: str) -> list[bpy.types.ID]:
    """A user appends the other file's index host itself."""
    import bpy

    with bpy.data.libraries.load(str(blend), link=False) as (_src, dst):  # ty: ignore[invalid-context-manager] - stubs
        setattr(dst, attr, [INDEX_HOST])
    return getattr(dst, attr)


def _assignment_is_copy() -> dict[str, Any]:
    """Whether assigning a record group copies it, and whether the copy's pointers are rewritten."""
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    a = bpy.data.collections.new("A")
    b = bpy.data.collections.new("B")
    a[KEY] = {"binding_id": BINDING, "self": a}
    b[KEY] = a[KEY]
    b[KEY]["binding_id"] = "changed"
    return {"source unchanged": a[KEY]["binding_id"] == BINDING, "copy's pointer": _label(b[KEY]["self"])}


def _without_scene(tmp: Path, link: bool) -> dict[str, list[str]]:
    """The control for append and link: a record without the scene pointer, into a file without "Dest"."""
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    dest = bpy.data.collections.new("Dest")
    bpy.data.scenes[0].collection.children.link(dest)
    dest[KEY] = {"binding_id": BINDING}
    source = tmp / "no-scene-pointer.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    before = {_label(s) for s in bpy.data.scenes}
    loaded = _load(source, "collections", link=link)
    return {
        "scenes added": sorted({_label(s) for s in bpy.data.scenes} - before),
        "loaded": [_label(c) for c in loaded],
    }


def _appended_host_users(blend: Path) -> dict[str, dict[str, Any]]:
    """Why an appended index host is not saved: its fake user and user count after append."""
    import bpy

    out = {}
    for attr in ("texts", "collections"):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        for host in _append_index(blend, attr):
            out[_label(host)] = {"fake user": host.use_fake_user, "users": host.users}
    return out


def _users() -> dict[str, dict[str, Any]]:
    """Users of the binding's datablocks with and without the records, and the destination's once unlinked."""
    import bpy

    out = {}
    for with_records in (True, False):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        dest = _tag_binding(with_records=with_records)
        scene, obj = bpy.data.scenes["Scene"], bpy.data.objects["Managed"]
        counts: dict[str, Any] = {_label(id_): id_.users for id_ in (scene, dest, obj)}
        scene.collection.children.unlink(dest)
        counts["destination's users once unlinked from the scene"] = dest.users
        out["with records" if with_records else "without records"] = counts
    return out


def _removed_destination(tmp: Path) -> dict[str, Any]:
    """What the records and the index hold once the destination is removed, before and after save and reopen."""
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.data.collections.remove(_tag_binding(with_records=True))
    pointers = {
        "scene's destination pointer": bpy.data.scenes["Scene"][KEY].get("destination"),
        "object's destination pointer": bpy.data.objects["Managed"][KEY].get("destination"),
    }
    before = {**pointers, "indexes": _indexes()}
    path = tmp / "removed.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    bpy.ops.wm.open_mainfile(filepath=str(path))
    return {**before, "reopened indexes": _indexes()}


def _window_manager(tmp: Path) -> dict[str, bool]:
    """The window manager as an index host: whether its record is saved, and whether another file opened keeps it."""
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.data.window_managers[0][INDEX] = {BINDING: "Dest"}
    path = tmp / "window-manager.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.open_mainfile(filepath=str(path))
    out = {"saved with the file": INDEX in bpy.data.window_managers[0]}
    for load_ui in (True, False):
        bpy.data.window_managers[0][INDEX] = {BINDING: "Dest"}
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=load_ui)
        out[f"session's record kept on opening a file with load_ui={load_ui}"] = INDEX in bpy.data.window_managers[0]
    return out
