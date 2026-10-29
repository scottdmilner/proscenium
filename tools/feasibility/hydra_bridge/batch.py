"""Apply a Hydra bridge plan as Geometry Nodes instances (M4, Phase D): the batched alternative to apply.py.

Plan objects that look the same except for their transform and constant primvars become instances on one
carrier object: those with the same mesh, material slots, destinations, and object color, and constant primvars
of the same names and kinds, and no two with the same transform. A group of one, a placeholder, and a copy with a
primvar no attribute can hold stay objects, as apply.py builds them.

- **Carriers:** three objects on one mesh of one point per instance. Its point attributes are each instance's
  world transform (a 4x4 matrix, so shear needs no parent), its element (`proscenium_element`, its plan index),
  its selection state, and its constant primvars by name, which reach the instance domain, where an Attribute
  node of type Instancer reads them. Each carrier's Geometry Nodes modifier instances the prototype on the points
  of one state, so a selection can select exactly its instances (batch_selection.py). The carriers' hide flags
  are the group's destinations.
- **Prototype:** an object no scene links, on the group's mesh, with the group's object-linked materials and
  object color, which every instance shows.
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

# Carrier point attributes, besides each instance's element (ELEMENT): its world transform and selection state.
TRANSFORM = "proscenium_transform"
STATE = "proscenium_state"
# The selection states, by value: each batch has a carrier per state, which shows the instances in it.
STATES = ("unselected", "selected", "active")
# The node group's inputs on a carrier: the object it instances, and the state whose points it instances.
PROTOTYPE_INPUT = "Prototype"
STATE_INPUT = "State"
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
    """A group's carriers and the prototype they instance, with the element of each point in point order."""

    carriers: list[bpy.types.Object]  # by state, on one points mesh
    prototype: bpy.types.Object
    elements: list[int]

    @property
    def points(self) -> bpy.types.Mesh:
        """The carriers' mesh."""
        return self.carriers[0].data  # ty: ignore[invalid-return-type] - Object.data is every kind of data


@dataclass(frozen=True)
class NodeGroup:
    """The carriers' node group, with its inputs' identifiers."""

    tree: bpy.types.GeometryNodeTree
    prototype_input: str
    state_input: str


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
    coincident: dict[tuple[Any, ...], int] = {}
    for index, record in enumerate(records):
        key = batch_key(record)
        if key is None:
            single.append(index)
            continue
        # A pick names an instance by its prototype and world matrix (batch_selection.py), so copies whose
        # transforms are equal go to separate batches, each with its own prototype.
        stored = (key, numpy.array(record["matrix"], dtype=numpy.float32).tobytes())
        repeat = coincident[stored] = coincident.get(stored, -1) + 1
        groups.setdefault((*key, repeat), []).append(index)
    single.extend(members[0] for members in groups.values() if len(members) == 1)
    tree = _node_group()
    shared = [members for members in groups.values() if len(members) > 1]
    batches = [
        _batch(number, members, records, meshes, materials, collection, tree) for number, members in enumerate(shared)
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
    tree: NodeGroup,
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
    _point_attribute(points, STATE, "INT", [0] * len(members))
    for name, value in first["properties"].items():
        data_type = attribute_type(value)
        assert data_type is not None  # batch_key left out copies with any other primvar
        _point_attribute(points, name, data_type, [records[i]["properties"][name] for i in members])

    carriers = []
    # Created in name order, so each sorts after the last: the unselected carrier, then "active", then "selected".
    for state, suffix in ((0, ""), (2, " active"), (1, " selected")):
        carrier = bpy.data.objects.new(f"Carrier {number:06d}{suffix}", points)
        collection.objects.link(carrier)
        carrier.hide_viewport = not first["viewport"]
        carrier.hide_render = not first["render"]
        modifier: Any = carrier.modifiers.new("Batch", "NODES")
        modifier.node_group = tree.tree
        # Blender 5's modifier inputs are structs by socket identifier, each holding its value, not ID properties.
        getattr(modifier.properties.inputs, tree.prototype_input).value = prototype
        getattr(modifier.properties.inputs, tree.state_input).value = state
        carriers.append((state, carrier))
    return Batch([carrier for _, carrier in sorted(carriers, key=lambda pair: pair[0])], prototype, members)


def _point_attribute(points: bpy.types.Mesh, name: str, data_type: str, values: list[Any]) -> None:
    prop, dtype = POINT_ATTRIBUTES[data_type]
    attribute: Any = points.attributes.new(name, data_type, "POINT")  # ty: ignore[invalid-argument-type]
    # The exact element type, or foreach_set silently reads item by item.
    attribute.data.foreach_set(prop, numpy.array(values, dtype=dtype).ravel())


def _node_group() -> NodeGroup:
    """Instance the Prototype input's object on the points in the State input's state, each with its transform."""
    tree: Any = bpy.data.node_groups.new(NODE_GROUP, "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    prototype_input = tree.interface.new_socket(PROTOTYPE_INPUT, in_out="INPUT", socket_type="NodeSocketObject")
    state_input = tree.interface.new_socket(STATE_INPUT, in_out="INPUT", socket_type="NodeSocketInt")
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
    state = nodes.new("GeometryNodeInputNamedAttribute")
    state.data_type = "INT"
    state.inputs["Name"].default_value = STATE
    shown = nodes.new("FunctionNodeCompare")
    shown.data_type, shown.operation = "INT", "EQUAL"
    links.new(state.outputs["Attribute"], shown.inputs[0])
    links.new(group_in.outputs[STATE_INPUT], shown.inputs[1])
    links.new(shown.outputs[0], instance.inputs["Selection"])
    links.new(group_in.outputs[PROTOTYPE_INPUT], info.inputs["Object"])
    links.new(group_in.outputs["Geometry"], instance.inputs["Points"])
    links.new(info.outputs["Geometry"], instance.inputs["Instance"])
    links.new(instance.outputs["Instances"], placed.inputs["Instances"])
    links.new(transform.outputs["Attribute"], placed.inputs["Transform"])
    links.new(placed.outputs["Instances"], group_out.inputs["Geometry"])
    return NodeGroup(tree, prototype_input.identifier, state_input.identifier)
