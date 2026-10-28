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
# The property each attribute data type's elements hold their value in.
ELEMENT_VALUES = {
    "FLOAT": "value",
    "FLOAT2": "vector",
    "FLOAT_VECTOR": "vector",
    "FLOAT_COLOR": "color",
    "INT": "value",
}


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
    objects = apply.apply(plan, collection).objects
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
        "color": list(obj.color),
        # The ID properties the bridge didn't add for itself: constant primvars by name.
        "properties": {k: _plain(obj[k]) for k in obj.keys() if not k.startswith("proscenium_")},
        "attributes": {} if mesh is None else _attributes(mesh),
        "uv_maps": [] if mesh is None else [layer.name for layer in mesh.uv_layers],
        "corner_verts": [] if mesh is None else [loop.vertex_index for loop in mesh.loops],
    }


def _plain(value: Any) -> Any:
    """An ID property value as JSON: arrays as (nested) lists."""
    return value.to_list() if hasattr(value, "to_list") else value


def _attributes(mesh: Any) -> dict[str, dict[str, Any]]:
    """The mesh's named attributes, Blender's internal ones aside: domain, data type, and each element's value."""
    result = {}
    for attribute in mesh.attributes:
        if attribute.name.startswith(".") or attribute.data_type not in ELEMENT_VALUES:
            continue
        prop = ELEMENT_VALUES[attribute.data_type]
        values = [getattr(element, prop) for element in attribute.data]
        result[attribute.name] = {
            "domain": attribute.domain,
            "data_type": attribute.data_type,
            "values": [v if isinstance(v, (int, float)) else list(v) for v in values],
        }
    return result


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


def replace_unit(module_dir: str, scene: str, unit: str, users: str, unmanaged: bool) -> dict[str, Any]:
    """Apply `scene`, then replace one unit of its display from the same plan (B6); what Blender holds around it.

    `unit` names one of update.py's sample units. With `unmanaged`, an object outside the display uses its mesh.
    """
    native = _native(module_dir)
    apply = importlib.import_module("apply")
    update = importlib.import_module("update")

    stage = Usd.Stage.Open(scene)
    bridge = native.Bridge(stage)
    plan = native.build_plan(bridge.capture())
    collection = bpy.data.collections.new("Baseline")
    blender_scene: Any = bpy.context.scene  # never None in a running Blender
    blender_scene.collection.children.link(collection)
    display = apply.apply(plan, collection)
    chosen = update.sample_units(plan.objects)[unit]
    outside = None
    if unmanaged:
        (mesh,) = (display.meshes[index] for index in chosen.meshes)
        outside = bpy.data.objects.new("Unmanaged", mesh)
        blender_scene.collection.objects.link(outside)
    before = _held(display, plan.objects)
    positions = None if outside is None else _positions(outside)
    counts = _counts()
    prepared = update.prepare(plan, display, chosen, update.UserPolicy(users))
    untouched = _held(display, plan.objects) == before and _linked(collection) == before["linked"]
    published = update.publish(prepared, display, collection)
    linked = _linked(collection)
    kept = update.retire(prepared)
    result = {
        "plan": [{"mesh": r["mesh"], "material_slots": list(r["material_slots"])} for r in plan.objects],
        "unit": {kind: sorted(getattr(chosen, kind)) for kind in ("objects", "meshes", "materials")},
        "before": before,
        "after": _held(published, plan.objects),
        "linked": {"published": linked, "retired": _linked(collection)},
        "counts": {"before": counts, "after": _counts()},
        "prepared_untouched": untouched,
        "kept": [i.as_pointer() for i in kept],
        "unmanaged": None
        if outside is None
        else {"data": _mesh_pointer(outside), "positions_kept": _positions(outside) == positions},
    }
    bridge.release()
    return result


def _held(display: Any, records: Any) -> dict[str, Any]:
    """Each object as Blender holds it (mesh by plan index), and the pointers of the display's data."""
    meshes = {mesh.as_pointer(): index for index, mesh in enumerate(display.meshes)}
    objects = []
    for record, obj in zip(records, display.objects, strict=True):
        facts = _object(record, obj)
        del facts["mesh"]  # Blender's name, which a replacement changes
        parent = obj.parent
        facts |= {
            "mesh_index": None if obj.data is None else meshes.get(obj.data.as_pointer()),
            "basis": _rows(obj.matrix_basis.transposed()),
            "parent_world": None if parent is None else _rows(parent.matrix_world.transposed()),
            "pointer": obj.as_pointer(),
            "data_pointer": None if obj.data is None else obj.data.as_pointer(),
        }
        objects.append(facts)
    return {
        "objects": objects,
        "meshes": [mesh.as_pointer() for mesh in display.meshes],
        "materials": [material.as_pointer() for material in display.materials],
        "linked": sorted(
            {p for obj in display.objects for p in (obj.as_pointer(), obj.parent and obj.parent.as_pointer()) if p}
        ),
    }


# A mesh object's data, read through Any: its Object.data is typed as every kind of object data.
def _mesh_pointer(obj: Any) -> int:
    return obj.data.as_pointer()


def _positions(obj: Any) -> list[list[float]]:
    return [list(v.co) for v in obj.data.vertices]


def _linked(collection: Any) -> list[int]:
    return sorted(obj.as_pointer() for obj in collection.objects)


def _counts() -> dict[str, int]:
    data = bpy.data
    return {
        "objects": len(data.objects),
        "meshes": len(data.meshes),
        "materials": len(data.materials),
        "collections": len(data.collections),
    }
