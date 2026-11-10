"""Isolated bodies: M4 Phase E (E6), a saved cached display reopened in a fresh process, with no bridge.

Runs in a fresh process (isolated/harness.py); see tests/isolated/test_cached.py.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import bpy

_spec = importlib.util.spec_from_file_location("isolated_body_caching", Path(__file__).with_name("caching.py"))
assert _spec is not None and _spec.loader is not None  # noqa: S101 - the sibling body
caching = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(caching)


def save(module_dir: str, dest: str, blend: str, times: list[float], sequence: bool) -> dict[str, Any]:
    """Cache frames.usda's `times`, the first building the display, and save it to `blend`.

    With `sequence`, its meshes cache in a USD file beside the scene, which is saved too. Returns each track's
    object's name, and the cache file, if any.
    """
    sys.path[:0] = [str(caching.BRIDGE), module_dir]
    native = importlib.import_module("_hydra_bridge")
    cached = importlib.import_module("cached_display")
    stage = caching._stage(dest)
    collection = bpy.data.collections.new("Cached")
    scene: Any = bpy.context.scene  # never None in a running Blender
    scene.collection.children.link(collection)
    scene.frame_set(int(times[0]))
    path = caching._sequence(dest, sequence)
    display = cached.CachedDisplay(native, stage, collection, times[0], sequence=path)
    handler = display.install_frame_change_handler(scene)
    try:
        for time in times[1:]:
            scene.frame_set(int(time))
        if path is not None:
            display.meshes.save()
        objects = [[key[0], list(key[1]), key[2], obj.name] for key, obj in display.objects.items()]
        bpy.ops.wm.save_as_mainfile(filepath=blend)
    finally:
        bpy.app.handlers.frame_change_pre.remove(handler)
        display.release()
    return {"objects": objects, "cache": path}


def reopen(  # noqa: PLR0913 - the saved display, and what to remove first
    module_dir: str, dest: str, blend: str, times: list[float], objects: list[list[Any]], remove: str | None
) -> dict[str, Any]:
    """Open `blend` with no bridge running, after removing the file `remove`, and show each of `times`.

    At each, reports where the display, as Blender evaluates it, differs from a fresh plan of the scene there: in
    each track's destinations, and for one in the viewport, its transform and its mesh.
    """
    if remove is not None:
        Path(remove).unlink()
    bpy.ops.wm.open_mainfile(filepath=blend)
    sys.path[:0] = [str(caching.BRIDGE), module_dir]
    native = importlib.import_module("_hydra_bridge")
    apply = importlib.import_module("object_display")
    frames = importlib.import_module("frame_capture")
    stage = caching.Usd.Stage.Open(os.path.join(dest, "frames.usda"))
    held = {(source, tuple(context), place): bpy.data.objects[name] for source, context, place, name in objects}
    scene: Any = bpy.context.scene  # never None in a running Blender
    found: dict[str, list[str]] = {}
    for time in times:
        scene.frame_set(int(time), subframe=time % 1)
        bridge = native.Bridge(stage)
        plan = native.build_plan(bridge.capture(time))
        bridge.release()
        records = dict(enumerate(plan.objects))
        fresh = {(*frames.copy_of(r), frames.place(i, records, {})): r for i, r in records.items()}
        depsgraph = bpy.context.evaluated_depsgraph_get()
        mismatches = [f"{key}: no object" for key in fresh.keys() - held.keys()]
        for key, obj in held.items():
            record = fresh.get(key)
            shown = (not obj.hide_viewport, not obj.hide_render)
            if shown != ((False, False) if record is None else (record["viewport"], record["render"])):
                mismatches.append(f"{key}: shown {shown}")
            if record is None or not shown[0]:
                continue
            basis = obj.matrix_basis if obj.parent is None else obj.parent.matrix_basis @ obj.matrix_basis
            if caching._moved({"matrix": caching._usd(basis)}, record):
                mismatches.append(f"{key}: transform")
            evaluated = obj.evaluated_get(depsgraph)
            mismatches += caching._content_mismatches(apply, key, evaluated, record, plan)
            mismatches += caching._topology_mismatches(key, evaluated, record, plan)
        found[str(time)] = sorted(mismatches)
    return {"mismatches": found}
