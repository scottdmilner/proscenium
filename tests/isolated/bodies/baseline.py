"""Isolated body: M4's object baseline, M1b's Hydra bridge and its apply.py, on a fixture's scene.

Runs in a fresh process (isolated/harness.py); see tests/isolated/test_baseline.py. Reports what Blender holds,
read back from Blender's data, so the test compares it with USD.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import bpy
from pxr import Usd

BRIDGE = Path(__file__).resolve().parents[3] / "tools/feasibility/hydra_bridge"


def _native(module_dir: str) -> Any:
    sys.path[:0] = [str(BRIDGE), module_dir]
    return importlib.import_module("_hydra_bridge")


def apply_scene(module_dir: str, scene: str) -> dict[str, Any]:
    """Capture, plan, and apply `scene` at default time; each object as Blender holds it, in plan order."""
    native = _native(module_dir)
    apply = importlib.import_module("apply")

    stage = Usd.Stage.Open(scene)
    bridge = native.Bridge(stage)
    snapshot = bridge.capture()
    plan = native.build_plan(snapshot)
    collection = bpy.data.collections.new("Baseline")
    blender_scene: Any = bpy.context.scene  # never None in a running Blender
    blender_scene.collection.children.link(collection)
    objects = apply.apply(plan, collection)
    reported = [_object(record, obj) for record, obj in zip(plan.objects, objects, strict=True)]
    # The depsgraph evaluates only objects shown in the viewport, so every object is shown before Blender's world
    # transforms are read, once its hide flags are reported.
    for obj in collection.objects:
        obj.hide_viewport = False
    view_layer: Any = bpy.context.view_layer  # never None in a running Blender
    view_layer.update()
    for entry, obj in zip(reported, objects, strict=True):
        entry["world"] = _rows(obj.matrix_world.transposed())  # USD's row-vector convention
        entry["shear_parent"] = None if obj.parent is None else obj.parent.get(apply.SHEAR_PARENT)
    result = {
        "objects": reported,
        "hydra_world": _hydra_world(snapshot),
        "errors": [d for d in plan.diagnostics if d["severity"] == "error"],
    }
    bridge.release()
    return result


def _rows(matrix: Any) -> list[list[float]]:
    return [[matrix[row][col] for col in range(4)] for row in range(4)]


def _hydra_world(snapshot: Any) -> dict[str, list[list[float]]]:
    """Hydra's own world transform of each mesh in a top-level instance: its matrix, then the instance's.

    The transform a Hydra consumer composes from the snapshot, before the planner's corrections; keyed by the
    drawn copy's USD path (instance location and the mesh's prototype-relative origin).
    """
    result = {}
    for path in snapshot.paths():
        prim = snapshot.prim(path)
        by = prim.get("instanced_by")
        if prim["type"] != "mesh" or not by:
            continue
        instancer = snapshot.prim(by["instancers"][0])
        if instancer.get("instanced_by"):  # nested: its frame is itself composed
            continue
        transforms = instancer["primvars"]["hydra:instanceTransforms"]["values"]
        for location, transform in zip(instancer["instancer"]["locations"], transforms, strict=True):
            result[f"{location}/{prim['origin']}"] = _rows(prim["matrix"] * transform)
    return result


def _object(record: Any, obj: Any) -> dict[str, Any]:
    mesh = obj.data if obj.type == "MESH" else None
    return {
        "source": obj["proscenium_source"],
        "plan_world": _rows(record["matrix"]),  # USD's row-vector convention
        "instance_context": list(obj["proscenium_instance_context"]),
        "placeholder": obj.get("proscenium_placeholder"),
        # Blender's own name for the mesh data, so objects that share it report the same name.
        "mesh": None if mesh is None else mesh.name,
        "viewport": not obj.hide_viewport,
        "render": not obj.hide_render,
        # Per material slot, the USD sources of the material it shows (None for none).
        "slots": [None if s.material is None else list(s.material["proscenium_sources"]) for s in obj.material_slots],
        "face_slots": [] if mesh is None else [p.material_index for p in mesh.polygons],
    }


def correspondence(module_dir: str, scene: str, times: list[float], unload: list[str]) -> dict[str, Any]:
    """The plan's correspondence for `scene` at each time, with the payloads in `unload` unloaded.

    Per time: each object's source entity, floor, and whether it is a viewport display element, and the universe.
    """
    native = _native(module_dir)
    stage = Usd.Stage.Open(scene)
    for path in unload:
        stage.Unload(path)
    bridge = native.Bridge(stage)
    generations = {}
    for time in times:
        plan = native.build_plan(bridge.capture(time))
        generations[str(time)] = {
            "objects": [
                {key: o[key] for key in ("source", "instance_context", "floor", "viewport")} for o in plan.objects
            ],
            "universe": plan.universe,
            "errors": [d for d in plan.diagnostics if d["severity"] == "error"],
        }
    bridge.release()
    return generations
