"""M4 Phase C (C5): the first ownership lookup after an undo, with the baseline's display as a binding's manifest.

The child applies the display into a file binding's destination, made through M3's API, so this writes its
manifest through M3's runtime: one entry per object, shear parent, placeholder mesh, mesh, and material. An
object entry covers its source and uses its mesh and materials; a mesh or material entry covers the sources of
its users, as M5's realistic covers would.

Every undo or redo drops the bindings' state, and the next lookup rebuilds it, reading every manifest
(lifecycle.md#undo-and-runtime-state). So after each undo and redo this times the first `ownership()` of an
object the step didn't change, then a second, cached one. The undo pushes, undos, and redos are timed too: they
are Blender's cost of an undo step at this scale, which background mode allows with global undo on.
"""

from __future__ import annotations

import statistics
import time
from functools import partial
from typing import TYPE_CHECKING, Any

import bpy

if TYPE_CHECKING:
    from collections.abc import Callable

REPEATS = 5


def _seconds(call: Callable[[], Any]) -> tuple[float, Any]:
    start = time.perf_counter()
    result = call()
    return time.perf_counter() - start, result


def _stats(values: list[float]) -> dict[str, Any]:
    return {
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "repeats": len(values),
        "values": values,  # in order: after the lookups, each undo then its redo
    }


def entries(display: Any, records: list[dict[str, Any]], materials: list[dict[str, Any]]) -> dict[str, Any]:
    """The display's manifest entries, by resource identity."""
    from apply import SHEAR_PARENT

    from proscenium.persistence.manifests import ManifestEntry

    users: dict[int, list[str]] = {}
    found: dict[str, Any] = {}
    for index, (record, obj) in enumerate(zip(records, display.objects, strict=True)):
        mesh = record["mesh"]
        uses = [] if mesh is None else [f"mesh:{mesh}"]
        uses += [f"material:{m}" for m in dict.fromkeys(record["material_slots"]) if m is not None]
        if mesh is not None:
            users.setdefault(mesh, []).append(record["source"])
        elif obj.data is not None:  # a placeholder's own bounds
            found[f"bounds:{index}"] = ManifestEntry(obj.data, [record["source"]], "placeholder bounds", [])
            uses.append(f"bounds:{index}")
        if obj.parent is not None and SHEAR_PARENT in obj.parent:
            found[f"shear:{index}"] = ManifestEntry(obj.parent, [record["source"]], "shear parent", [])
        found[f"object:{index}"] = ManifestEntry(obj, [record["source"]], "object", uses)
    for index, mesh in enumerate(display.meshes):
        found[f"mesh:{index}"] = ManifestEntry(mesh, sorted(set(users.get(index, []))), "mesh", [])
    for index, material in enumerate(display.materials):
        found[f"material:{index}"] = ManifestEntry(material, list(materials[index]["sources"]), "material", [])
    return found


def measure(binding_id: Any, display: Any, records: list[dict[str, Any]], materials: list[dict[str, Any]]) -> dict:
    """Write the manifest, then time undo, redo, and the lookups after each."""
    from proscenium import runtime
    from proscenium.persistence.manifests import Manifest

    preferences: Any = bpy.context.preferences  # never None in a running Blender
    preferences.edit.use_global_undo = True
    built, manifest = _seconds(lambda: Manifest(entries(display, records, materials)))
    written, _ = _seconds(lambda: runtime.set_manifest(binding_id, manifest))
    # An object no step below changes, found by name after each undo, since undo re-reads datablocks.
    name = display.objects[-1].name
    moved = display.objects[0].name
    # Found before each timing: Blender finds a datablock by name by scanning the list.
    target = bpy.data.objects[name]
    lookup, owned = _seconds(lambda: runtime.ownership(target))
    pushes, undos, redos, first, cached = [], [], [], [], []
    rebuilds = runtime.rebuild_count()
    seconds, _ = _seconds(lambda: bpy.ops.ed.undo_push(message="published"))
    pushes.append(seconds)
    for step in range(REPEATS):
        bpy.data.objects[moved].location.x += 1.0
        seconds, _ = _seconds(lambda step=step: bpy.ops.ed.undo_push(message=f"edit {step}"))
        pushes.append(seconds)
        for undone, times in ((bpy.ops.ed.undo, undos), (bpy.ops.ed.redo, redos)):
            seconds, _ = _seconds(undone)
            times.append(seconds)
            target = bpy.data.objects[name]
            seconds, result = _seconds(partial(runtime.ownership, target))
            first.append(seconds)
            assert result.status == owned.status, (result, owned)
            seconds, _ = _seconds(partial(runtime.ownership, target))
            cached.append(seconds)
    return {
        "entries": len(manifest.entries),
        # It changes as the undo or redo handlers drop the state, before and after, and as the next lookup
        # rebuilds it: three times for each.
        "rebuild_count changes": runtime.rebuild_count() - rebuilds,
        "undos and redos": len(undos) + len(redos),
        "status": str(owned.status),
        "timings": {
            "build the manifest": built,
            "set_manifest": written,
            "ownership after the write": lookup,
            "undo push": _stats(pushes),
            "undo": _stats(undos),
            "redo": _stats(redos),
            "first ownership after undo or redo": _stats(first),
            "cached ownership": _stats(cached),
        },
    }
