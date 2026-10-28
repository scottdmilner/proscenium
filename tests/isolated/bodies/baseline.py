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
    plan = native.build_plan(bridge.capture())
    collection = bpy.data.collections.new("Baseline")
    blender_scene: Any = bpy.context.scene  # never None in a running Blender
    blender_scene.collection.children.link(collection)
    objects = apply.apply(plan, collection)
    bridge.release()
    return {
        "objects": [_object(obj) for obj in objects],
        "errors": [d for d in plan.diagnostics if d["severity"] == "error"],
    }


def _object(obj: Any) -> dict[str, Any]:
    mesh = obj.data if obj.type == "MESH" else None
    return {
        "source": obj["proscenium_source"],
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
