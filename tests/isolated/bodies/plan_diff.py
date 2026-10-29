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
KITS = "/World/SharedPrototype"


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
        elif edit == "instance-transform":  # moves one copy of each of the kit's batches
            stage.GetPrimAtPath(f"{KITS}/KitB").GetAttribute("xformOp:translate").Set(Gf.Vec3d(3, 2, 0))
        elif edit == "instance-remove":  # leaves two copies in each of the kit's batches
            stage.GetPrimAtPath(f"{KITS}/KitA").SetActive(False)
        elif edit == "instance-remove-another":  # leaves one copy of each of the kit's meshes, so no batch
            stage.GetPrimAtPath(f"{KITS}/KitB").SetActive(False)
        elif edit == "instance-restore":
            for kit in ("KitA", "KitB"):
                stage.GetPrimAtPath(f"{KITS}/{kit}").SetActive(True)
        elif edit == "instance-color":  # recolors every copy of one of the kit's batches
            UsdGeom.PrimvarsAPI(stage.GetPrimAtPath("/Prototypes/Kit/Body")).GetPrimvar("displayColor").Set(
                [Gf.Vec3f(0, 0, 1)]
            )
        elif edit == "holes":  # a build problem, which later plans reuse with the build (D9)
            UsdGeom.Mesh(stage.GetPrimAtPath(f"{EQUAL}/MeshE")).GetHoleIndicesAttr().Set([0])
        elif edit == "subset":  # moves face 2 between Partitioned's subsets, which alone change
            mesh = "/World/FaceAssignments/Partitioned"
            stage.GetPrimAtPath(f"{mesh}/Even").GetAttribute("indices").Set([0])
            stage.GetPrimAtPath(f"{mesh}/Odd").GetAttribute("indices").Set([1, 2, 3])
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


def reuse_edits(module_dir: str, scene: str, edits: list[str], point_instancers: bool = False) -> list[dict[str, Any]]:
    """Plan `scene`, then after each edit plan it twice: from scratch, and reusing the previous plan's builds (D9).

    Each step reports whether the two plans are the same in everything Python reads, and how many meshes each
    built, from the planner's own count. The reusing plans chain: each step reuses the previous step's.
    """
    sys.path[:0] = [str(BRIDGE), module_dir]
    native = importlib.import_module("_hydra_bridge")
    stage = Usd.Stage.Open(scene, Usd.Stage.LoadAll)
    bridge = native.Bridge(stage)
    plan = native.build_plan(bridge.capture(), point_instancers=point_instancers)
    steps = []
    for edit in edits:
        _edit(stage, edit)
        snapshot = bridge.capture(incremental=True)
        native.take_filter_timings()
        fresh = native.build_plan(snapshot, point_instancers=point_instancers)
        fresh_built = native.take_filter_timings()["plan: build mesh"][0]
        reused = native.build_plan(snapshot, point_instancers=point_instancers, previous=plan)
        built = native.take_filter_timings()["plan: build mesh"][0]
        differing = [name for name in PLAN_FIELDS if _plain(getattr(fresh, name)) != _plain(getattr(reused, name))]
        steps.append({"edit": edit, "differing": differing, "built": built, "fresh_built": fresh_built})
        plan = reused
    bridge.release()
    return steps


# What Python reads of a plan.
PLAN_FIELDS = ("objects", "meshes", "materials", "diagnostics", "universe")


def _plain(value: Any) -> Any:
    """A plan view's value as comparable data: buffers as their bytes, containers recursively."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    try:
        return bytes(memoryview(value))
    except TypeError:
        return value


def _objects(plan: Any) -> list[dict[str, Any]]:
    return [{"source": o["source"], "mesh": o["mesh"], "slots": list(o["material_slots"])} for o in plan.objects]


def _baseline() -> Any:
    """The baseline body, for its reading of what Blender holds."""
    spec = importlib.util.spec_from_file_location("isolated_body_baseline", Path(__file__).with_name("baseline.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def update_edits(
    module_dir: str, scene: str, edits: list[str], users: str, representation: str = "objects"
) -> list[dict[str, Any]]:
    """Apply `scene`'s plan, then update the display to the plan after each edit in turn, by its diff.

    `representation` is the baseline's "objects" (apply.py and update.py) or Phase D's "batched" (batch.py and
    batch_update.py). Every element is selected before each edit. Each step reports the diff, what the display
    held before and after, what the updated display holds against a fresh application of the same plan, and
    Blender's data counts for each.
    """
    sys.path[:0] = [str(BRIDGE), module_dir]
    native = importlib.import_module("_hydra_bridge")
    batched = representation == "batched"
    apply = importlib.import_module("batch" if batched else "apply")
    update = importlib.import_module("batch_update" if batched else "update")
    selection = importlib.import_module("batch_selection" if batched else "selection")
    policy = importlib.import_module("update").UserPolicy(users)
    baseline = _baseline()
    held_by = baseline.batched_held if batched else baseline._held  # noqa: SLF001 - the sibling body's reader

    stage = Usd.Stage.Open(scene, Usd.Stage.LoadAll)
    bridge = native.Bridge(stage)
    plan = native.build_plan(bridge.capture())
    collection = bpy.data.collections.new("Baseline")
    blender_scene: Any = bpy.context.scene  # never None in a running Blender
    blender_scene.collection.children.link(collection)
    view_layer = blender_scene.view_layers[0]
    display = (apply.apply_batched if batched else apply.apply)(plan, collection)
    steps = []
    for edit in edits:
        selected = set(range(len(plan.objects)))
        selection.apply_selection(view_layer, display if batched else collection, selected, set())
        before = held_by(display, plan.objects)
        _edit(stage, edit)
        following = native.build_plan(bridge.capture(incremental=True))
        diff = native.diff_plans(plan, following)
        prepared = update.prepare(following, diff, display, policy)
        display = update.publish(prepared, display, collection)
        linked = {"published": _linked(collection), "expected": _published(display, batched)}
        update.retire(prepared)
        records = following.objects
        held = held_by(display, records)
        counts = baseline._counts()  # noqa: SLF001
        fresh_collection = bpy.data.collections.new("Fresh")
        blender_scene.collection.children.link(fresh_collection)  # so the depsgraph evaluates its carriers
        fresh = (apply.apply_batched if batched else apply.apply)(following, fresh_collection)
        fresh_held = held_by(fresh, records)
        fresh_counts = baseline._counts()  # noqa: SLF001
        _remove(fresh, fresh_collection, batched)
        steps.append(
            {
                "edit": edit,
                "diff": diff,
                "before": _pointers(before),
                "after": _pointers(held),
                "held": [_values(o) for o in held["objects"]],
                "fresh": [_values(o) for o in fresh_held["objects"]],
                "elements": [obj["proscenium_element"] for obj in _objects_of(display)],
                "selected": held["selected"],
                "linked": linked,
                "counts": counts,
                "fresh_counts": {kind: fresh_counts[kind] - counts[kind] for kind in counts},
                "written": _written(prepared, batched),
            }
        )
        plan = following
    bridge.release()
    return steps


def _remove(fresh: Any, collection: Any, batched: bool) -> None:
    """Remove a fresh application and everything it created."""
    created = [*collection.all_objects, *fresh.meshes, *fresh.materials, collection]
    if batched:
        created += [batch.prototype for batch in fresh.batches] + [batch.points for batch in fresh.batches]
        created.append(fresh.nodes.tree)
    bpy.data.batch_remove(created)
    bpy.data.orphans_purge(do_recursive=True)  # the placeholders' own bounds meshes


def _linked(collection: Any) -> list[int]:
    return sorted(obj.as_pointer() for obj in collection.objects)


def _published(display: Any, batched: bool) -> list[int]:
    """What the published display links: its objects, their shear parents, and a batched display's carriers."""
    objects = _objects_of(display)
    linked = [*objects, *(obj.parent for obj in objects if obj.parent is not None)]
    if batched:
        linked += [carrier for batch in display.batches for carrier in batch.carriers]
    return sorted(obj.as_pointer() for obj in linked)


def _objects_of(display: Any) -> list[Any]:
    """The display's objects in plan order: all of them, or for a batched display, those kept as objects."""
    objects = display.objects
    return list(objects.values()) if isinstance(objects, dict) else objects


def _written(prepared: Any, batched: bool) -> dict[str, Any]:
    """What an update wrote to Blender, by kind; a staging collection is a Blender write too."""
    written = {
        "created": len(prepared.created),
        "repointed": len(prepared.repointed),
        "renumbered": len(prepared.renumbered),
        "retired": len(prepared.retired),
        "staged": prepared.staging is not None,
    }
    if batched:
        written |= {
            "added": len(prepared.added),
            "dropped": len(prepared.dropped),
            "points": sum(rebatch.points is not None for rebatch in prepared.kept),
            "reprototyped": sum(rebatch.reprototyped for rebatch in prepared.kept),
            "renumbered batches": sum(rebatch.renumbered for rebatch in prepared.kept),
        }
    return written


def _pointers(held: dict[str, Any]) -> dict[str, Any]:
    """The pointers of a display's objects (None for an instance), meshes, materials, and batches."""
    return {
        "objects": [o.get("pointer") for o in held["objects"]],
        "meshes": held["meshes"],
        "materials": held["materials"],
        "batches": held.get("batches", []),
    }


def _values(held: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in held.items() if key not in ("pointer", "data_pointer")}
