"""M4 Phase C: the update scenarios of acceptance.md's Performance section, as edits to the live stage.

Each scenario after the initial synchronization makes one change that the next capture sees. The edit's target
is chosen from the published plan, so the same scenario runs on ALab and on the generated update scenes:
- unchanged: nothing, a manual refresh;
- transform: a translation of the first mesh object outside instances, from the session layer;
- instance-transform (Phase D): a translation of the first instanced copy's outermost instance root, which moves
  one copy of each of its meshes, from the session layer;
- shared-geometry: the points of the instanced mesh with the most copies, scaled by 1.01;
- material: a constant surface input of the material in the most slots whose prim is outside instances;
- payload-unload and payload-load: every payload unloaded from a stage opened with them loaded, or loaded into
  one opened without;
- time-step: the next time code, which on the update scenes changes a mesh's topology.

A prim inside a native instance takes no opinion from the session layer, so the shared geometry is edited in
the layer that defines it, in memory only: no layer is ever saved.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

import numpy as np
from pxr import Gf, Usd, UsdGeom, UsdShade, Vt

if TYPE_CHECKING:
    from plan_types import ObjectRecord, Plan

SCENARIOS = (
    "initial",
    "unchanged",
    "transform",
    "instance-transform",
    "shared-geometry",
    "material",
    "payload-unload",
    "payload-load",
    "time-step",
)


def load_set(scenario: str) -> Usd.Stage.InitialLoadSet:
    """What the stage opens with: payload-load starts without payloads."""
    return Usd.Stage.LoadNone if scenario == "payload-load" else Usd.Stage.LoadAll


def edit(scenario: str, stage: Usd.Stage, plan: Plan, time: float) -> tuple[float, dict[str, Any]]:
    """Make the scenario's change; returns the time code to capture next and what was changed."""
    records = plan.objects
    if scenario == "unchanged":
        return time, {}
    if scenario == "transform":
        source = next(r["source"] for r in records if not r["instance_context"] and r["mesh"] is not None)
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            op = UsdGeom.Xformable(stage.GetPrimAtPath(source)).AddTranslateOp(opSuffix="phase_c")
            op.Set(Gf.Vec3d(0.01, 0, 0))
        return time, {"prim": source}
    if scenario == "instance-transform":
        root = next(r["instance_context"][0] for r in records if r["instance_context"] and r["mesh"] is not None)
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            op = UsdGeom.Xformable(stage.GetPrimAtPath(root)).AddTranslateOp(opSuffix="phase_d")
            op.Set(Gf.Vec3d(0.01, 0, 0))
        return time, {"instance root": root}
    if scenario == "shared-geometry":
        return time, _shared_geometry(stage, records, time)
    if scenario == "material":
        return time, _material(stage, plan, records, time)
    if scenario == "payload-unload":
        stage.Unload("/")
        return time, {"unloaded": "/"}
    if scenario == "payload-load":
        stage.Load("/")
        return time, {"loaded": "/"}
    if scenario == "time-step":
        return time + 1, {"time": time + 1}
    raise ValueError(f"no edit for scenario {scenario}")


def _shared_geometry(stage: Usd.Stage, records: list[ObjectRecord], time: float) -> dict[str, Any]:
    copies = Counter(r["mesh"] for r in records if r["instance_context"] and r["mesh"] is not None)
    mesh, count = copies.most_common(1)[0]
    source = next(r["source"] for r in records if r["mesh"] == mesh and r["instance_context"])
    prototype = stage.GetPrimAtPath(source).GetPrimInPrototype()
    points = UsdGeom.Mesh(prototype).GetPointsAttr()
    scaled = Vt.Vec3fArray.FromNumpy((np.array(points.Get(time), dtype=np.float32) * 1.01).astype(np.float32))
    spec = next(
        s for s in points.GetPropertyStack(time) if s.HasDefaultValue() or s.layer.GetNumTimeSamplesForPath(s.path)
    )
    if spec.layer.GetNumTimeSamplesForPath(spec.path):
        spec.layer.SetTimeSample(spec.path, time, scaled)
    else:
        spec.default = scaled
    return {"prim": source, "copies": count, "layer": spec.layer.identifier, "spec": str(spec.path)}


def _material(stage: Usd.Stage, plan: Plan, records: list[ObjectRecord], time: float) -> dict[str, Any]:
    slotted = Counter(m for r in records for m in set(r["material_slots"]) if m is not None)
    for index, users in slotted.most_common():
        for source in plan.materials[index]["sources"]:
            prim = stage.GetPrimAtPath(source)
            if not prim or prim.IsInstanceProxy():
                continue
            shader, _, _ = UsdShade.Material(prim).ComputeSurfaceSource()
            for shader_input in shader.GetInputs() if shader else []:
                value = shader_input.Get(time)
                if shader_input.HasConnectedSource() or not isinstance(value, (float, Gf.Vec3f)):
                    continue
                with Usd.EditContext(stage, stage.GetSessionLayer()):
                    shader_input.Set(value * 0.5 if isinstance(value, Gf.Vec3f) else value * 0.5 + 0.1)
                return {"material": source, "input": shader_input.GetBaseName(), "objects": users}
    raise RuntimeError("no material outside instances with a constant input")
