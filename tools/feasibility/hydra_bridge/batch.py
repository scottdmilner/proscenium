"""Apply a Hydra bridge plan as Geometry Nodes instances (M4, Phase D): the batched alternative to apply.py.

Plan objects that look the same except for their transform and constant primvars become instances on one
carrier object: those with the same mesh, material slots, destinations, and object color, and constant primvars
of the same names and kinds. A group of one, a placeholder, and a copy with a primvar no attribute can hold stay
objects, as apply.py builds them.

- **Carrier:** a mesh of one point per instance. Its point attributes are each instance's world transform (a
  4x4 matrix, so shear needs no parent), its element (`proscenium_element`, its plan index), and its constant
  primvars by name, which reach the instance domain, where an Attribute node of type Instancer reads them. Its
  hide flags are the group's destinations.
- **Prototype:** an object no scene links, on the group's mesh, with the group's object-linked materials and
  object color, which every instance shows. The carrier's Geometry Nodes modifier instances it on every point.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import bpy
import numpy
from apply import new_material, new_mesh, new_object
from selection import ELEMENT

if TYPE_CHECKING:
    from plan_types import ObjectRecord, Plan, PropertyValue

# Carrier point attributes, besides each instance's element (ELEMENT): its world transform.
TRANSFORM = "proscenium_transform"
# On a carrier object: the node group's input that names its prototype.
PROTOTYPE_INPUT = "Prototype"
NODE_GROUP = "proscenium_batch"

# The property foreach_set writes and the element type Blender stores, by attribute data type.
POINT_ATTRIBUTES = {
    "BOOLEAN": ("value", numpy.bool_),
    "INT": ("value", numpy.int32),
    "FLOAT": ("value", numpy.float32),
    "FLOAT2": ("vector", numpy.float32),
    "FLOAT_VECTOR": ("vector", numpy.float32),
    "FLOAT4X4": ("value", numpy.float32),
}


@dataclass(frozen=True)
class Batch:
    """A carrier and the prototype it instances, with the element of each instance in instance order."""

    carrier: bpy.types.Object
    prototype: bpy.types.Object
    elements: list[int]


@dataclass(frozen=True)
class BatchedDisplay:
    """What a batched application holds."""

    objects: dict[int, bpy.types.Object]  # by element: the plan objects kept as objects
    batches: list[Batch]
    meshes: list[bpy.types.Mesh]
    materials: list[bpy.types.Material]


def attribute_type(value: PropertyValue) -> str | None:
    """The attribute data type that holds a constant primvar's property value, or None if none can."""
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "INT"
    if isinstance(value, float):
        return "FLOAT"
    if isinstance(value, list) and all(isinstance(v, float) for v in value):
        return {2: "FLOAT2", 3: "FLOAT_VECTOR"}.get(len(value))
    return None


def batch_key(record: ObjectRecord) -> tuple[Any, ...] | None:
    """What instances of one carrier share, or None for an object that stays an object."""
    kinds = {name: attribute_type(value) for name, value in record["properties"].items()}
    if record["mesh"] is None or None in kinds.values():
        return None
    return (
        record["mesh"],
        tuple(record["material_slots"]),
        record["viewport"],
        record["render"],
        _color(record),
        tuple(sorted(kinds.items())),
    )


def apply_batched(plan: Plan, collection: bpy.types.Collection) -> BatchedDisplay:
    """Create the plan's materials and meshes, a carrier per group of two or more, and objects for the rest."""
    records = plan.objects
    materials = [new_material(data) for data in plan.materials]
    meshes = [new_mesh(data) for data in plan.meshes]
    groups: dict[tuple[Any, ...], list[int]] = {}
    single: list[int] = []
    for index, record in enumerate(records):
        key = batch_key(record)
        if key is None:
            single.append(index)
        else:
            groups.setdefault(key, []).append(index)
    single.extend(members[0] for members in groups.values() if len(members) == 1)
    tree, prototype_input = _node_group()
    shared = [members for members in groups.values() if len(members) > 1]
    batches = [
        _batch(number, members, records, meshes, materials, collection, (tree, prototype_input))
        for number, members in enumerate(shared)
    ]
    objects = {index: new_object(index, records[index], meshes, materials, collection) for index in sorted(single)}
    return BatchedDisplay(objects, batches, meshes, materials)


def _color(record: ObjectRecord) -> tuple[float, ...]:
    """The object color apply.py gives a copy: its constant displayColor and displayOpacity, or white."""
    color = record["primvars"].get("displayColor")
    opacity = record["primvars"].get("displayOpacity")
    rgb = tuple(color[0]) if color is not None and len(color) == 1 else (1.0, 1.0, 1.0)
    return (*rgb, opacity[0] if opacity is not None and len(opacity) == 1 else 1.0)


def _batch(  # noqa: PLR0913 - a carrier's whole context
    number: int,
    members: list[int],
    records: list[ObjectRecord],
    meshes: list[bpy.types.Mesh],
    materials: list[bpy.types.Material],
    collection: bpy.types.Collection,
    nodes: tuple[bpy.types.GeometryNodeTree, str],  # the node group and its prototype input's identifier
) -> Batch:
    first = records[members[0]]
    mesh = first["mesh"]
    assert mesh is not None  # batch_key left out placeholders
    # Numbered in creation order, so each new name sorts last (C3).
    prototype = bpy.data.objects.new(f"Prototype {number:06d}", meshes[mesh])
    for slot, material in zip(prototype.material_slots, first["material_slots"], strict=True):
        slot.link = "OBJECT"
        slot.material = None if material is None else materials[material]
    prototype.color = _color(first)

    points = bpy.data.meshes.new(f"Carrier {number:06d}")
    points.vertices.add(len(members))
    # USD's row-vector matrix, flattened row by row, is Blender's column-major 4x4 attribute layout.
    _point_attribute(points, TRANSFORM, "FLOAT4X4", [records[i]["matrix"] for i in members])
    _point_attribute(points, ELEMENT, "INT", members)
    for name, value in first["properties"].items():
        data_type = attribute_type(value)
        assert data_type is not None  # batch_key left out copies with any other primvar
        _point_attribute(points, name, data_type, [records[i]["properties"][name] for i in members])

    carrier = bpy.data.objects.new(f"Carrier {number:06d}", points)
    collection.objects.link(carrier)
    carrier.hide_viewport = not first["viewport"]
    carrier.hide_render = not first["render"]
    modifier: Any = carrier.modifiers.new("Batch", "NODES")
    tree, prototype_input = nodes
    modifier.node_group = tree
    # Blender 5's modifier inputs are structs by socket identifier, each holding its value, not ID properties.
    getattr(modifier.properties.inputs, prototype_input).value = prototype
    return Batch(carrier, prototype, members)


def _point_attribute(points: bpy.types.Mesh, name: str, data_type: str, values: list[Any]) -> None:
    prop, dtype = POINT_ATTRIBUTES[data_type]
    attribute: Any = points.attributes.new(name, data_type, "POINT")  # ty: ignore[invalid-argument-type]
    # The exact element type, or foreach_set silently reads item by item.
    attribute.data.foreach_set(prop, numpy.array(values, dtype=dtype).ravel())


def _node_group() -> tuple[bpy.types.GeometryNodeTree, str]:
    """Instance the Prototype input's object on every point, with the point's transform; and that input's identifier."""
    tree: Any = bpy.data.node_groups.new(NODE_GROUP, "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    prototype_input = tree.interface.new_socket(PROTOTYPE_INPUT, in_out="INPUT", socket_type="NodeSocketObject")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = tree.nodes, tree.links
    group_in, group_out = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    info = nodes.new("GeometryNodeObjectInfo")
    info.inputs["As Instance"].default_value = True
    instance = nodes.new("GeometryNodeInstanceOnPoints")
    transform = nodes.new("GeometryNodeInputNamedAttribute")
    transform.data_type = "FLOAT4X4"
    transform.inputs["Name"].default_value = TRANSFORM
    placed = nodes.new("GeometryNodeSetInstanceTransform")
    links.new(group_in.outputs[PROTOTYPE_INPUT], info.inputs["Object"])
    links.new(group_in.outputs["Geometry"], instance.inputs["Points"])
    links.new(info.outputs["Geometry"], instance.inputs["Instance"])
    links.new(instance.outputs["Instances"], placed.inputs["Instances"])
    links.new(transform.outputs["Attribute"], placed.inputs["Transform"])
    links.new(placed.outputs["Instances"], group_out.inputs["Geometry"])
    return tree, prototype_input.identifier
