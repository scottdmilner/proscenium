"""Isolated body: M4's plan diff (C1), between the plan before and after one edit to a fixture's stage.

Runs in a fresh process (isolated/harness.py); see tests/isolated/test_plan_diff.py. Edits go to the session
layer of the caller's stage, and the bridge recaptures incrementally, as a refresh would.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

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
