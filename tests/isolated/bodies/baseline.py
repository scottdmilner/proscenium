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


def apply_scene(module_dir: str, scene: str, representation: str = "objects", minimum: int = 2) -> dict[str, Any]:
    """Capture, plan, and apply `scene` at default time; each plan object as Blender displays it, in plan order.

    `representation` is the baseline's "objects" (apply.py) or Phase D's "batched" (batch.py), where an instance
    reports its prototype's mesh and materials, its carrier's destinations, and its own transform and attributes.
    `minimum` is the batched display's smallest batch.
    """
    native = _native(module_dir)
    apply = importlib.import_module("apply")

    stage = Usd.Stage.Open(scene)
    bridge = native.Bridge(stage)
    snapshot = bridge.capture()
    plan = native.build_plan(snapshot)
    records = plan.objects
    collection = bpy.data.collections.new("Baseline")
    blender_scene: Any = bpy.context.scene  # never None in a running Blender
    blender_scene.collection.children.link(collection)
    if representation == "objects":
        objects = dict(enumerate(apply.apply(plan, collection).objects))
        batches = []
    else:
        display = importlib.import_module("batch").apply_batched(plan, collection, minimum)
        objects, batches = display.objects, display.batches
    reported: dict[int, dict[str, Any]] = {}
    for element, obj in objects.items():
        reported[element] = _object(records[element], obj)
    # The depsgraph evaluates only objects shown in the viewport, so every object is shown before Blender's world
    # transforms are read, once its hide flags are reported.
    carriers = [carrier for batch in batches for carrier in batch.carriers]
    shown = {c.name: (not c.hide_viewport, not c.hide_render) for c in carriers}
    for obj in collection.objects:
        obj.hide_viewport = False
    view_layer: Any = bpy.context.view_layer  # never None in a running Blender
    view_layer.update()
    for element, obj in objects.items():
        reported[element]["world"] = _rows(obj.matrix_world.transposed())  # USD's row-vector convention
        reported[element]["shear_parent"] = None if obj.parent is None else obj.parent.get(apply.SHEAR_PARENT)
        reported[element]["instance"] = False
    for element, entry in _instances(view_layer, batches, shown).items():
        assert element not in reported, element  # each element is displayed once
        del entry["carrier"]
        reported[element] = {"source": records[element]["source"], "plan_world": _rows(records[element]["matrix"])}
        reported[element] |= {"instance_context": list(records[element]["instance_context"]), **entry}
    result = {
        "objects": [reported[element] for element in range(len(records))],
        "batches": len(batches),
        "hydra_world": _hydra_world(snapshot),
        "errors": [d for d in plan.diagnostics if d["severity"] == "error"],
    }
    bridge.release()
    return result


def _instances(view_layer: Any, batches: list[Any], shown: dict[str, tuple[bool, bool]]) -> dict[int, dict[str, Any]]:
    """Each carrier's evaluated instances, by the element its instance attributes name."""
    depsgraph = view_layer.depsgraph
    attributes = {}
    for carrier in (carrier for batch in batches for carrier in batch.carriers):
        # The instances' point cloud lives only as long as the geometry set that holds it.
        geometry = carrier.evaluated_get(depsgraph).evaluated_geometry()
        instances = geometry.instances_pointcloud()  # None for a carrier with no instances
        if instances is not None:
            attributes[carrier.name] = _attributes(instances)
    found = {}
    for instance in depsgraph.object_instances:
        carrier = instance.parent.original if instance.is_instance and instance.parent else None
        if carrier is None or carrier.name not in attributes:
            continue
        held = attributes[carrier.name]
        index = instance.persistent_id[1]  # the instance's index in its carrier's instances (ad hoc, Blender 5.2)
        element = held["proscenium_element"]["values"][index]
        assert element not in found, element  # one carrier shows each point
        viewport, render = shown[carrier.name]
        found[element] = {
            **_shown(instance.instance_object.original),
            "placeholder": None,
            "viewport": viewport,
            "render": render,
            "world": _rows(instance.matrix_world.transposed()),
            "shear_parent": None,
            "instance": True,
            "carrier": carrier.name,
            # The instance attributes the bridge didn't add for itself, constant primvars by name, and the
            # prototype's ID properties.
            "properties": {
                name: a["values"][index]
                for name, a in held.items()
                if name != "position" and not name.startswith("proscenium_")
            }
            | _object_properties(instance.instance_object.original),
        }
    return found


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
    return {
        "source": obj["proscenium_source"],
        "plan_world": _rows(record["matrix"]),  # USD's row-vector convention
        "instance_context": list(obj["proscenium_instance_context"]),
        "placeholder": obj.get("proscenium_placeholder"),
        "viewport": not obj.hide_viewport,
        "render": not obj.hide_render,
        # The ID properties the bridge didn't add for itself: constant primvars by name.
        "properties": _object_properties(obj),
        **_shown(obj),
    }


def _object_properties(obj: Any) -> dict[str, Any]:
    """The ID properties the bridge didn't add for itself: constant primvars by name."""
    return {k: _plain(obj[k]) for k in obj.keys() if not k.startswith("proscenium_")}


def _shown(obj: Any) -> dict[str, Any]:
    """What an object shows of its mesh and materials."""
    mesh = obj.data if obj.type == "MESH" else None
    return {
        # Blender's own name for the mesh data, so objects that share it report the same name.
        "mesh": None if mesh is None else mesh.name,
        # Per material slot, the USD sources of the material it shows (None for none).
        "slots": [None if s.material is None else list(s.material["proscenium_sources"]) for s in obj.material_slots],
        "face_slots": [] if mesh is None else [p.material_index for p in mesh.polygons],
        "color": list(obj.color),
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
    prepared = update.prepare(plan, update.unit_diff(plan, chosen), display, update.UserPolicy(users))
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
    objects = [_held_object(record, obj, meshes) for record, obj in zip(records, display.objects, strict=True)]
    return {
        "objects": objects,
        "meshes": [mesh.as_pointer() for mesh in display.meshes],
        "materials": [material.as_pointer() for material in display.materials],
        "selected": [element for element, obj in enumerate(display.objects) if obj.select_get()],
        "linked": sorted(
            {p for obj in display.objects for p in (obj.as_pointer(), obj.parent and obj.parent.as_pointer()) if p}
        ),
    }


def _held_object(record: Any, obj: Any, meshes: dict[int, int]) -> dict[str, Any]:
    """An object as Blender holds it, its mesh by plan index from `meshes` (by pointer), with its pointers."""
    facts = _object(record, obj)
    del facts["mesh"]  # Blender's name, which a replacement changes
    parent = obj.parent
    return facts | {
        "mesh_index": None if obj.data is None else meshes.get(obj.data.as_pointer()),
        "basis": _rows(obj.matrix_basis.transposed()),
        "parent_world": None if parent is None else _rows(parent.matrix_world.transposed()),
        "pointer": obj.as_pointer(),
        "data_pointer": None if obj.data is None else obj.data.as_pointer(),
    }


def batched_held(display: Any, records: Any) -> dict[str, Any]:
    """A batched display as Blender holds and evaluates it, in plan order, and the pointers of its parts.

    An object reports as _held reports it, and an instance as apply_scene reports it, with its prototype's mesh
    by plan index. The carriers are shown while the display is read, then hidden again as they were.
    """
    meshes = {mesh.as_pointer(): index for index, mesh in enumerate(display.meshes)}
    carriers = [carrier for batch in display.batches for carrier in batch.carriers]
    shown = {c.name: (not c.hide_viewport, not c.hide_render) for c in carriers}
    hidden = [(carrier, carrier.hide_viewport) for carrier in carriers]
    for carrier in carriers:
        carrier.hide_viewport = False
    view_layer: Any = bpy.context.view_layer  # never None in a running Blender
    view_layer.update()
    # Read once evaluated, as a shear parent's world matrix is, after an earlier update or not.
    held = {element: _held_object(records[element], obj, meshes) for element, obj in display.objects.items()}
    names = {mesh.name: index for index, mesh in enumerate(display.meshes)}
    # Selected: an object selected in Blender, or an instance in the viewport on a carrier other than the
    # unselected one. Blender's selection holds no object hidden in the viewport.
    selected = [element for element, obj in display.objects.items() if obj.select_get(view_layer=view_layer)]
    states = {carrier.name: state for batch in display.batches for state, carrier in enumerate(batch.carriers)}
    for element, entry in _instances(view_layer, display.batches, shown).items():
        assert element not in held, element  # each element is displayed once
        mesh = entry.pop("mesh")
        if states[entry.pop("carrier")] != 0 and entry["viewport"]:
            selected.append(element)
        held[element] = {"source": records[element]["source"], "mesh_index": names.get(mesh), **entry}
    for carrier, hide in hidden:
        carrier.hide_viewport = hide
    view_layer.update()
    return {
        "objects": [held[element] for element in range(len(records))],
        "batches": [
            {
                "elements": list(batch.elements),
                "carriers": [carrier.as_pointer() for carrier in batch.carriers],
                "prototype": batch.prototype.as_pointer(),
                "points": batch.points.as_pointer(),
            }
            for batch in display.batches
        ],
        "meshes": [mesh.as_pointer() for mesh in display.meshes],
        "materials": [material.as_pointer() for material in display.materials],
        "selected": sorted(selected),
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


def detach_scene(module_dir: str, scene: str, blend: str, representation: str = "objects") -> dict[str, Any]:
    """Apply `scene`, edit its display in Blender, detach it, and save to `blend` (B7); Blender's data around detach.

    The edits come before detach, which must keep them: an object whose mesh others share is deleted, another
    is moved, and a material is recolored. In the batched display (`representation` "batched", D4), the first
    batch's unselected carrier, if there is one, is deleted too.
    """
    native = _native(module_dir)
    detach = importlib.import_module("detach")

    stage = Usd.Stage.Open(scene)
    bridge = native.Bridge(stage)
    plan = native.build_plan(bridge.capture())
    collection = bpy.data.collections.new("Baseline")
    blender_scene: Any = bpy.context.scene  # never None in a running Blender
    blender_scene.collection.children.link(collection)
    if representation == "objects":
        display = importlib.import_module("apply").apply(plan, collection)
        objects = display.objects
    else:
        display = importlib.import_module("batch").apply_batched(plan, collection)
        objects = list(display.objects.values())
        if display.batches:
            bpy.data.objects.remove(display.batches[0].carriers[0])
    shared: list[Any] = [obj for obj in objects if obj.type == "MESH" and obj.data.users > 1]
    deleted = shared[0].name
    bpy.data.objects.remove(shared[0])
    shared[1].location.x += 1.0
    recolored = None
    if display.materials:
        display.materials[0].diffuse_color = (1.0, 0.0, 1.0, 1.0)
        recolored = display.materials[0].name
    before = _blender_data()
    released = detach.detach(collection)
    after = _blender_data()
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    bridge.release()
    return {
        "before": before,
        "after": after,
        "released": {
            "objects": released.objects,
            "materials": released.materials,
            "properties": released.properties,
            "carriers": released.carriers,
            "attributes": released.attributes,
        },
        "deleted": deleted,
        "recolored": recolored,
    }


def read_blend(blend: str) -> dict[str, Any]:
    """Blender's data in `blend`, opened without the bridge."""
    bpy.ops.wm.open_mainfile(filepath=blend)
    return _blender_data()


def _blender_data() -> dict[str, Any]:
    """Every object, mesh, material, and collection as Blender holds it, by name, with all its ID properties.

    Also, by the name of the object that instances them, how many instances Blender evaluates.
    """
    view_layer: Any = bpy.context.view_layer  # never None in a running Blender
    view_layer.update()
    instances: dict[str, int] = {}
    for instance in view_layer.depsgraph.object_instances:
        if instance.is_instance and instance.parent is not None:
            name = instance.parent.original.name
            instances[name] = instances.get(name, 0) + 1
    return {
        "instances": instances,
        "objects": {obj.name: _object_data(obj) for obj in bpy.data.objects},
        "meshes": {
            mesh.name: {
                "users": mesh.users,
                "vertices": len(mesh.vertices),
                "faces": len(mesh.polygons),
                "attributes": sorted(a.name for a in mesh.attributes),
                "properties": _properties(mesh),
            }
            for mesh in bpy.data.meshes
        },
        "materials": {
            material.name: {"diffuse": list(material.diffuse_color), "properties": _properties(material)}
            for material in bpy.data.materials
        },
        "collections": {c.name: sorted(obj.name for obj in c.objects) for c in bpy.data.collections},
    }


def _object_data(obj: Any) -> dict[str, Any]:
    return {
        "type": obj.type,
        "data": None if obj.data is None else obj.data.name,
        "parent": None if obj.parent is None else obj.parent.name,
        "basis": _rows(obj.matrix_basis),
        "parent_inverse": _rows(obj.matrix_parent_inverse),
        "hide": [obj.hide_viewport, obj.hide_render, obj.hide_select],
        "display": [obj.display_type, obj.empty_display_type],
        "color": list(obj.color),
        "slots": [[slot.link, None if slot.material is None else slot.material.name] for slot in obj.material_slots],
        "collections": sorted(c.name for c in obj.users_collection),
        "properties": _properties(obj),
        "modifiers": [_modifier(modifier) for modifier in obj.modifiers],
    }


def _modifier(modifier: Any) -> dict[str, Any]:
    """A modifier's type, and a Geometry Nodes modifier's node group and the objects its inputs name."""
    tree = getattr(modifier, "node_group", None)
    if tree is None:
        return {"type": modifier.type}
    sockets = [item for item in tree.interface.items_tree if item.item_type == "SOCKET" and item.in_out == "INPUT"]
    inputs = modifier.properties.inputs
    return {
        "type": modifier.type,
        "node_group": tree.name,
        "inputs": {
            s.name: _plain(value.name if isinstance(value, bpy.types.ID) else value)
            for s in sockets
            if s.socket_type != "NodeSocketGeometry"
            for value in [getattr(inputs, s.identifier).value]
        },
    }


def _properties(datablock: Any) -> dict[str, Any]:
    return {key: _plain(datablock[key]) for key in datablock.keys()}
