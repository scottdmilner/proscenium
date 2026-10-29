"""Apply a Hydra bridge plan as Geometry Nodes instances (M4, Phase D): the batched alternative to apply.py.

Plan objects that look the same except for their transform and constant primvars become instances on one
carrier object: those with the same mesh, material slots, destinations, and object color, and constant primvars
of the same names and kinds, and no two with the same transform. Only a group of at least a minimum size becomes
a batch, since a batch is four Blender objects. A smaller group, a placeholder, and a copy with a primvar no
attribute can hold stay objects, as apply.py builds them. The bridge's module forms the groups (`plan.batch_groups`,
batch_groups.h), so an update needn't convert and regroup every plan record in Python.

Instances leave out constant string primvars, which apply.py keeps on an object as ID properties: no shading node
reads a string, so they neither split a group nor reach its batch.

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
from apply import new_material, new_mesh, new_object, object_color
from selection import ELEMENT

if TYPE_CHECKING:
    from collections.abc import Mapping

    from plan_types import ObjectRecord, Plan, PropertyValue

# Carrier point attributes, besides each instance's element (ELEMENT): its world transform and selection state.
TRANSFORM = "proscenium_transform"
STATE = "proscenium_state"
# The selection states, by value: each batch has a carrier per state, which shows the instances in it.
STATES = ("unselected", "selected", "active")
# The smallest group that becomes a batch, unless a caller asks for larger ones.
MINIMUM = 2
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
    key: tuple[Any, ...]  # its group's key in the plan it was applied from (plan.batch_groups)

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
    nodes: NodeGroup
    serial: int  # the number the next batch or points mesh takes, so its names sort last (C3)
    minimum: int  # the smallest group that becomes a batch


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


def groups(plan: Plan, minimum: int) -> tuple[dict[tuple[Any, ...], list[int]], list[int]]:
    """The plan objects in batches of at least `minimum`, by their group's key, and the rest, in plan order.

    A key is (mesh, material slots, in the viewport, in the render, object color, (primvar, attribute type)
    pairs, repeat); copies whose transforms are equal are in separate groups, by repeat, since a pick names an
    instance by its prototype and world matrix (batch_selection.py).
    """
    shared, single = plan.batch_groups(minimum)
    return dict(shared), single


def apply_batched(plan: Plan, collection: bpy.types.Collection, minimum: int = MINIMUM) -> BatchedDisplay:
    """Create the plan's materials and meshes, a batch per group of `minimum` or more, and objects for the rest."""
    assert minimum >= 2  # a batch of one would be four objects for one copy
    records = dict(enumerate(plan.objects))
    materials = [new_material(data) for data in plan.materials]
    meshes = [new_mesh(data) for data in plan.meshes]
    shared, single = groups(plan, minimum)
    nodes = _node_group()
    batches = [
        new_batch(number, key, members, records, meshes, materials, collection, nodes)
        for number, (key, members) in enumerate(shared.items())
    ]
    objects = {index: new_object(index, records[index], meshes, materials, collection) for index in single}
    return BatchedDisplay(objects, batches, meshes, materials, nodes, len(batches), minimum)


def prototype_of(carrier: bpy.types.Object) -> bpy.types.Object | None:
    """The object a carrier's modifier instances, or None if it has none."""
    for modifier in carrier.modifiers:
        tree: Any = getattr(modifier, "node_group", None)
        if modifier.type != "NODES" or tree is None:
            continue
        for item in tree.interface.items_tree:
            if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name == PROTOTYPE_INPUT:
                return getattr(modifier.properties.inputs, item.identifier).value  # ty: ignore[unresolved-attribute]
    return None


def new_batch(  # noqa: PLR0913 - a batch's whole context
    number: int,
    key: tuple[Any, ...],
    members: list[int],
    records: Mapping[int, ObjectRecord],
    meshes: list[bpy.types.Mesh],
    materials: list[bpy.types.Material],
    collection: bpy.types.Collection,
    nodes: NodeGroup,
) -> Batch:
    """Batch `number` of plan objects `members`, which share `key`: its prototype, points, and carriers."""
    first = records[members[0]]
    mesh = first["mesh"]
    assert mesh is not None  # the groups leave out placeholders
    # Numbered in creation order, so each new name sorts last (C3).
    prototype = bpy.data.objects.new(f"Prototype {number:06d}", meshes[mesh])
    set_prototype(prototype, first, meshes, materials)
    points = new_points(number, members, records, [0] * len(members))
    carriers = []
    # Created in name order, so each sorts after the last: the unselected carrier, then "active", then "selected".
    for state, suffix in ((0, ""), (2, " active"), (1, " selected")):
        carrier = bpy.data.objects.new(f"Carrier {number:06d}{suffix}", points)
        collection.objects.link(carrier)
        carrier.hide_viewport = not first["viewport"]
        carrier.hide_render = not first["render"]
        modifier: Any = carrier.modifiers.new("Batch", "NODES")
        modifier.node_group = nodes.tree
        # Blender 5's modifier inputs are structs by socket identifier, each holding its value, not ID properties.
        getattr(modifier.properties.inputs, nodes.prototype_input).value = prototype
        getattr(modifier.properties.inputs, nodes.state_input).value = state
        carriers.append((state, carrier))
    return Batch([carrier for _, carrier in sorted(carriers, key=lambda pair: pair[0])], prototype, members, key)


def set_prototype(
    prototype: bpy.types.Object,
    record: ObjectRecord,
    meshes: list[bpy.types.Mesh],
    materials: list[bpy.types.Material],
) -> None:
    """Put a group's mesh, object-linked materials, and object color on its prototype, changing only what differs."""
    mesh = record["mesh"]
    assert mesh is not None  # the groups leave out placeholders
    if prototype.data != meshes[mesh]:
        # The same slot count, and the slots link to the object, so each keeps its place.
        prototype.data = meshes[mesh]
    for slot, material in zip(prototype.material_slots, record["material_slots"], strict=True):
        if slot.link != "OBJECT":
            slot.link = "OBJECT"
        wanted = None if material is None else materials[material]
        if slot.material != wanted:
            slot.material = wanted
    color = object_color(record)
    if list(prototype.color) != numpy.array(color, dtype=numpy.float32).tolist():  # as Blender stores it
        prototype.color = color


def new_points(number: int, members: list[int], records: Mapping[int, ObjectRecord], held: list[int]) -> bpy.types.Mesh:
    """A batch's points mesh: one point per member, with its transform, element, state `held`, and primvars."""
    points = bpy.data.meshes.new(f"Carrier {number:06d}")
    points.vertices.add(len(members))
    # USD's row-vector matrix, flattened row by row, is Blender's column-major 4x4 attribute layout.
    _point_attribute(points, TRANSFORM, "FLOAT4X4", [records[i]["matrix"] for i in members])
    _point_attribute(points, ELEMENT, "INT", members)
    _point_attribute(points, STATE, "INT", held)
    for name, value in _primvars(records[members[0]]).items():
        data_type = attribute_type(value)
        assert data_type is not None  # the groups leave out copies with any other primvar
        _point_attribute(points, name, data_type, [records[i]["properties"][name] for i in members])
    return points


def _primvars(record: ObjectRecord) -> dict[str, PropertyValue]:
    """A copy's constant primvars that instances hold: all but its strings."""
    return {name: value for name, value in record["properties"].items() if not isinstance(value, str)}


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
