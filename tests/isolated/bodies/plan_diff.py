"""Isolated body: M4's plan diff (C1), and the updates it drives (C2), after edits to a fixture's stage.

Runs in a fresh process (isolated/harness.py); see tests/isolated/test_plan_diff.py and test_update.py. Edits go
to the session layer of the caller's stage, and the bridge recaptures incrementally, as a refresh would.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import bpy
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

BRIDGE = Path(__file__).resolve().parents[3] / "tools/feasibility/hydra_bridge"
EQUAL = "/World/EqualContent"


def _edit(stage: Usd.Stage, edit: str) -> None:
    session = stage.GetSessionLayer()
    with Usd.EditContext(stage, session):
        if edit == "transform":
            UsdGeom.Xformable(stage.GetPrimAtPath(f"{EQUAL}/MeshD")).AddTranslateOp(opSuffix="moved").Set(
                Gf.Vec3d(0, 1, 0)
            )
        elif edit == "shared-geometry":
            points = UsdGeom.Mesh(stage.GetPrimAtPath("/Prototypes/Kit/Body")).GetPointsAttr()
            points.Set([p * 2 for p in points.Get()])
        elif edit == "material":
            shader = UsdShade.Shader(stage.GetPrimAtPath("/World/Looks/Red/Surface"))
            shader.GetInput("diffuseColor").Set(Gf.Vec3f(0.9, 0.2, 0.2))
        elif edit == "primvar":
            UsdGeom.PrimvarsAPI(stage.GetPrimAtPath(f"{EQUAL}/MeshB")).GetPrimvar("displayColor").Set(
                [Gf.Vec3f(0.9, 0.9, 0.9)]
            )
        elif edit == "visibility":
            UsdGeom.Imageable(stage.GetPrimAtPath(f"{EQUAL}/MeshA")).MakeInvisible()
        elif edit == "structure":
            stage.GetPrimAtPath(f"{EQUAL}/MeshC").SetActive(False)
            Sdf.CreatePrimInLayer(session, EQUAL)
            Sdf.CopySpec(stage.GetRootLayer(), f"{EQUAL}/MeshA", session, f"{EQUAL}/MeshNew")
        elif edit == "unload":
            stage.Unload("/World/Payload")
        elif edit == "load":
            stage.Load("/World/Payload")
        elif edit != "unchanged":
            raise ValueError(edit)


def diff_edits(module_dir: str, scene: str, edits: list[str]) -> list[dict[str, Any]]:
    """Plan `scene` at default time, then after each edit in turn; each step's diff from the previous plan."""
    sys.path[:0] = [str(BRIDGE), module_dir]
    native = importlib.import_module("_hydra_bridge")
    stage = Usd.Stage.Open(scene, Usd.Stage.LoadAll)
    bridge = native.Bridge(stage)
    plan = native.build_plan(bridge.capture())
    steps = []
    for edit in edits:
        _edit(stage, edit)
        following = native.build_plan(bridge.capture(incremental=True))
        steps.append(
            {
                "edit": edit,
                "diff": native.diff_plans(plan, following),
                "old": _objects(plan),
                "new": _objects(following),
                "meshes": len(following.meshes),
                "materials": [m["sources"] for m in following.materials],
            }
        )
        plan = following
    bridge.release()
    return steps


def _objects(plan: Any) -> list[dict[str, Any]]:
    return [{"source": o["source"], "mesh": o["mesh"], "slots": list(o["material_slots"])} for o in plan.objects]


def _baseline() -> Any:
    """The baseline body, for its reading of what Blender holds."""
    spec = importlib.util.spec_from_file_location("isolated_body_baseline", Path(__file__).with_name("baseline.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def update_edits(module_dir: str, scene: str, edits: list[str], users: str) -> list[dict[str, Any]]:
    """Apply `scene`'s plan, then update the display to the plan after each edit in turn, by its diff.

    Each step reports the diff, the display's pointers before and after, what the updated display holds against
    a fresh application of the same plan, and Blender's data counts for each.
    """
    sys.path[:0] = [str(BRIDGE), module_dir]
    native = importlib.import_module("_hydra_bridge")
    apply = importlib.import_module("apply")
    update = importlib.import_module("update")
    baseline = _baseline()

    stage = Usd.Stage.Open(scene, Usd.Stage.LoadAll)
    bridge = native.Bridge(stage)
    plan = native.build_plan(bridge.capture())
    collection = bpy.data.collections.new("Baseline")
    blender_scene: Any = bpy.context.scene  # never None in a running Blender
    blender_scene.collection.children.link(collection)
    display = apply.apply(plan, collection)
    steps = []
    for edit in edits:
        _edit(stage, edit)
        following = native.build_plan(bridge.capture(incremental=True))
        diff = native.diff_plans(plan, following)
        before = _pointers(display)
        prepared = update.prepare(following, diff, display, update.UserPolicy(users))
        display = update.publish(prepared, display, collection)
        update.retire(prepared)
        records = following.objects
        held = baseline._held(display, records)  # noqa: SLF001 - the sibling body's reader
        counts = baseline._counts()  # noqa: SLF001
        fresh_collection = bpy.data.collections.new("Fresh")
        fresh = apply.apply(following, fresh_collection)
        fresh_held = baseline._held(fresh, records)  # noqa: SLF001
        fresh_counts = baseline._counts()  # noqa: SLF001
        bpy.data.batch_remove([*fresh_collection.all_objects, *fresh.meshes, *fresh.materials, fresh_collection])
        bpy.data.orphans_purge(do_recursive=True)  # the placeholders' own bounds meshes
        steps.append(
            {
                "edit": edit,
                "diff": diff,
                "before": before,
                "after": _pointers(display),
                "held": [_values(o) for o in held["objects"]],
                "fresh": [_values(o) for o in fresh_held["objects"]],
                "elements": [obj["proscenium_element"] for obj in display.objects],
                "counts": counts,
                "fresh_counts": {kind: fresh_counts[kind] - counts[kind] for kind in counts},
                "written": {
                    "created": len(prepared.created),
                    "repointed": len(prepared.repointed),
                    "renumbered": len(prepared.renumbered),
                    "retired": len(prepared.retired),
                    "staged": prepared.staging is not None,  # a staging collection is a Blender write too
                },
            }
        )
        plan = following
    bridge.release()
    return steps


def _pointers(display: Any) -> dict[str, list[int]]:
    return {
        "objects": [obj.as_pointer() for obj in display.objects],
        "meshes": [mesh.as_pointer() for mesh in display.meshes],
        "materials": [material.as_pointer() for material in display.materials],
    }


def _values(held: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in held.items() if key not in ("pointer", "data_pointer")}
