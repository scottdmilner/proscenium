"""Sample attributes: a mesh's values at cached time codes, which a frames modifier shows (M7 plan, D3).

Ported from the bridge's attribute_samples.py and keyframes.py ([M4 plan](M04-prototypes.md), E5). A mesh whose
attributes vary holds each cached time code's values of each varying attribute as an attribute `<name>@<sample>`
beside it, numbered in the order samples arrive. A Geometry Nodes group per set of varying attributes, the frames
group, stores each over its attribute for the sample its modifier's keyed `Sample` input names, where it has one, and
removes the samples; sample BASE, which no attribute has, shows the mesh's own values. The modifier is made first in
its object's stack, so it acts before any other. M7's keys are constant, so the group has the bridge's one input, not
its blending inputs, and M7 samples only a bounds mesh's positions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    import bpy

FRAME_SEPARATOR = "@"  # a sample's attribute is <name>@<sample>
MODIFIER = "Proscenium frames"
BASE = -1  # the sample of a mesh's own values, which no attribute has
SAMPLE = "Sample"  # the modifier input naming the sample shown, keyed constant through its socket identifier
_SAMPLE_SOCKET = "Socket_1"  # the first input after the geometry
# The varying attributes: name, data type, domain.
type Signature = tuple[tuple[str, str, str], ...]
POSITIONS: Signature = (("position", "FLOAT_VECTOR", "POINT"),)  # a bounds mesh's, the one set M7 samples


def populate_frames_group(tree: bpy.types.NodeTree, signature: Signature) -> None:
    """Populate an allocated frames group, storing each attribute's sample for the Sample input where it has one.

    It then removes the attribute's samples.
    """
    interface: Any = tree.interface  # the stubs restrict socket_type to DEFAULT
    interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    socket = interface.new_socket(SAMPLE, in_out="INPUT", socket_type="NodeSocketInt")
    if socket.identifier != _SAMPLE_SOCKET:  # the keys name it
        raise RuntimeError(f"Expected input {SAMPLE} to be {_SAMPLE_SOCKET}, not {socket.identifier}")
    interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes: Any = tree.nodes
    links = tree.links
    group_input = nodes.new("NodeGroupInput")
    geometry = group_input.outputs[0]
    sample_text = nodes.new("FunctionNodeValueToString")
    links.new(group_input.outputs[SAMPLE], next(i for i in sample_text.inputs if i.enabled))
    for name, data_type, domain in signature:
        prefix = nodes.new("FunctionNodeInputString")
        prefix.string = f"{name}{FRAME_SEPARATOR}"
        join = nodes.new("GeometryNodeStringJoin")
        links.new(sample_text.outputs[0], join.inputs["Strings"])  # Join Strings puts its newest link first
        links.new(prefix.outputs[0], join.inputs["Strings"])
        named = nodes.new("GeometryNodeInputNamedAttribute")
        named.data_type = data_type
        links.new(join.outputs[0], named.inputs["Name"])
        store = nodes.new("GeometryNodeStoreNamedAttribute")
        store.data_type, store.domain = data_type, domain
        store.inputs["Name"].default_value = name
        links.new(geometry, store.inputs["Geometry"])
        links.new(named.outputs["Exists"], store.inputs["Selection"])
        links.new(named.outputs["Attribute"], store.inputs["Value"])
        # Then its samples: a wildcard pattern holds one asterisk.
        remove = nodes.new("GeometryNodeRemoveAttribute")
        remove.inputs["Pattern Mode"].default_value = "Wildcard"
        remove.inputs["Name"].default_value = f"{name}{FRAME_SEPARATOR}*"
        links.new(store.outputs[0], remove.inputs["Geometry"])
        geometry = remove.outputs[0]
    links.new(geometry, nodes.new("NodeGroupOutput").inputs[0])


def sample_input_path() -> str:
    """The data path of a frames modifier's Sample input, which its keys name."""
    return f'modifiers["{MODIFIER}"].properties.inputs.{_SAMPLE_SOCKET}.value'


def new_frames_modifier(obj: bpy.types.Object, group: bpy.types.NodeTree) -> bpy.types.Modifier:
    """A frames modifier on obj showing group, made first in its stack."""
    modifier: Any = obj.modifiers.new(MODIFIER, "NODES")
    modifier.node_group = group
    if len(obj.modifiers) > 1:
        obj.modifiers.move(len(obj.modifiers) - 1, 0)
    return modifier


def sample_count(mesh: bpy.types.Mesh, name: str) -> int:
    """How many samples of attribute name mesh holds, which is the next sample's number."""
    return sum(1 for a in mesh.attributes if a.name.startswith(f"{name}{FRAME_SEPARATOR}"))


def add_sample(mesh: bpy.types.Mesh, name: str, data_type: str, domain: str, values: Sequence[float]) -> str:
    """Add the next sample of attribute name to mesh, holding values flattened; its attribute's name."""
    sample_name = f"{name}{FRAME_SEPARATOR}{sample_count(mesh, name)}"
    attributes: Any = mesh.attributes  # the stubs type data_type and domain as literals
    attribute = attributes.new(sample_name, data_type, domain)
    attribute.data.foreach_set("vector", values)
    return sample_name


def remove_attribute(mesh: bpy.types.Mesh, name: str) -> None:
    """Remove mesh's attribute name, if it has one."""
    if (attribute := mesh.attributes.get(name)) is not None:
        mesh.attributes.remove(attribute)
