"""The attribute caches of a cached display's meshes (M4 Phase E, E3): sample attributes, and the group reading them.

A mesh whose topology holds caches each synchronization's values of each varying attribute as an attribute
`<name>@<sample>` beside it, numbered in the order samples arrive. A Geometry Nodes group per set of varying
attributes stores each over its attribute for the sample its modifier's keyed `Sample` input names, where it has
one, and with blending mixes it with the next sample's (cached.py).
"""

from __future__ import annotations

from typing import Any

import bpy
import numpy
from apply import Layer

FRAME_SEPARATOR = "@"  # a sample's attribute is <name>@<sample>
MODIFIER = "proscenium frames"
BASE = -1  # the sample of a mesh's own values, which no attribute has
# The modifier inputs, in order after the geometry: the sample shown, and with blending the next one and both their
# time codes. Each is keyed constant through its socket identifier, which follows the order.
SAMPLE, NEXT, TIME, NEXT_TIME = "Sample", "Next sample", "Time", "Next time"
INPUTS = {name: f"Socket_{i}" for i, name in enumerate((SAMPLE, NEXT, TIME, NEXT_TIME), start=1)}
# A data type's in a mix, for the types that blend.
BLENDED = {"FLOAT": "FLOAT", "FLOAT2": "VECTOR", "FLOAT_VECTOR": "VECTOR", "FLOAT_COLOR": "RGBA"}
type Signature = tuple[tuple[str, str, str], ...]  # the varying attributes: name, data type, domain


def frames_group(signature: Signature, blend: bool = False) -> bpy.types.NodeTree:
    """A node group storing each attribute of `signature` from its attribute for the `Sample` input.

    Only where that sample has one; it then removes the attribute's samples. With `blend`, a float attribute is
    mixed with the next sample's by the scene's time between their time codes, either side taking the mesh's own
    values where its sample has none.
    """
    tree: Any = bpy.data.node_groups.new("Proscenium frames", "GeometryNodeTree")
    tree["proscenium_frames"] = [name for name, _, _ in signature]
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    for name in (SAMPLE, NEXT, TIME, NEXT_TIME) if blend else (SAMPLE,):
        kind = "NodeSocketInt" if name in (SAMPLE, NEXT) else "NodeSocketFloat"
        socket = tree.interface.new_socket(name, in_out="INPUT", socket_type=kind)
        if socket.identifier != INPUTS[name]:  # the keys name it
            raise RuntimeError(f"Expected input {name} to be {INPUTS[name]}, not {socket.identifier}")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = tree.nodes, tree.links
    group_input = nodes.new("NodeGroupInput")
    geometry = group_input.outputs[0]
    texts = {}
    for name in (SAMPLE, NEXT) if blend else (SAMPLE,):
        texts[name] = nodes.new("FunctionNodeValueToString")
        links.new(group_input.outputs[name], next(i for i in texts[name].inputs if i.enabled))
    weight = _weight(tree, group_input) if blend else None
    for name, data_type, domain in signature:
        prefix = nodes.new("FunctionNodeInputString")
        prefix.string = f"{name}{FRAME_SEPARATOR}"

        def read(sample: str, name: str = name, data_type: str = data_type, prefix: Any = prefix) -> Any:
            join = nodes.new("GeometryNodeStringJoin")
            links.new(texts[sample].outputs[0], join.inputs["Strings"])  # Join Strings puts its newest link first
            links.new(prefix.outputs[0], join.inputs["Strings"])
            named = nodes.new("GeometryNodeInputNamedAttribute")
            named.data_type = stored_type(data_type)
            links.new(join.outputs[0], named.inputs["Name"])
            return named

        named = read(SAMPLE)
        store = nodes.new("GeometryNodeStoreNamedAttribute")
        store.data_type, store.domain = data_type, domain
        store.inputs["Name"].default_value = name
        links.new(geometry, store.inputs["Geometry"])
        if weight is not None and data_type in BLENDED:
            own = nodes.new("GeometryNodeInputNamedAttribute")
            own.data_type = stored_type(data_type)
            own.inputs["Name"].default_value = name
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = BLENDED[data_type]
            sides = [i for i in mix.inputs if i.enabled]  # the factor, then A and B
            links.new(weight, sides[0])
            for side, sample in zip(sides[1:], (named, read(NEXT)), strict=True):
                switch = nodes.new("GeometryNodeSwitch")
                switch.input_type = BLENDED[data_type]
                links.new(sample.outputs["Exists"], switch.inputs["Switch"])
                links.new(own.outputs["Attribute"], switch.inputs["False"])
                links.new(sample.outputs["Attribute"], switch.inputs["True"])
                links.new(switch.outputs[0], side)
            links.new(next(o for o in mix.outputs if o.enabled), store.inputs["Value"])
        else:
            links.new(named.outputs["Exists"], store.inputs["Selection"])
            links.new(named.outputs["Attribute"], store.inputs["Value"])
        # Then its samples: a wildcard pattern holds one asterisk.
        remove = nodes.new("GeometryNodeRemoveAttribute")
        remove.inputs["Pattern Mode"].default_value = "Wildcard"
        remove.inputs["Name"].default_value = f"{name}{FRAME_SEPARATOR}*"
        links.new(store.outputs[0], remove.inputs["Geometry"])
        geometry = remove.outputs[0]
    links.new(geometry, nodes.new("NodeGroupOutput").inputs[0])
    return tree


def _weight(tree: Any, group_input: Any) -> Any:
    """The scene's time between the sample's time code and the next's, from 0 to 1; 0 when they are one."""
    nodes, links = tree.nodes, tree.links
    since, span, ratio = (nodes.new("ShaderNodeMath") for _ in range(3))
    since.operation, span.operation, ratio.operation = "SUBTRACT", "SUBTRACT", "DIVIDE"  # divide by 0 gives 0
    ratio.use_clamp = True
    links.new(nodes.new("GeometryNodeInputSceneTime").outputs["Frame"], since.inputs[0])
    links.new(group_input.outputs[TIME], since.inputs[1])
    links.new(group_input.outputs[NEXT_TIME], span.inputs[0])
    links.new(group_input.outputs[TIME], span.inputs[1])
    links.new(since.outputs[0], ratio.inputs[0])
    links.new(span.outputs[0], ratio.inputs[1])
    return ratio.outputs[0]


def input_path(name: str) -> str:
    """A modifier input's path, which its keys name."""
    return f'modifiers["{MODIFIER}"].properties.inputs.{INPUTS[name]}.value'


def stored_type(data_type: str) -> str:
    # A 2D vector on corners would be a UV map, so a sample's is stored as a 3D vector.
    return "FLOAT_VECTOR" if data_type == "FLOAT2" else data_type


def stored(layer: Layer) -> Layer:
    """A layer as its sample attribute holds it."""
    if layer.data_type != "FLOAT2":
        return layer
    padded = numpy.zeros((len(layer.values) // 2, 3), numpy.float32)
    padded[:, :2] = layer.values.reshape(-1, 2)
    return Layer(layer.name, "FLOAT_VECTOR", layer.domain, layer.prop, padded.ravel())


def sample_mesh(mesh: bpy.types.Mesh, sample: int, varying: dict[str, Layer]) -> bpy.types.Mesh:
    """A copy of `mesh` showing `sample` of its `varying` attributes, without its samples."""
    copy: Any = mesh.copy()
    for name, layer in varying.items() if sample != BASE else ():
        attribute = copy.attributes.get(f"{name}{FRAME_SEPARATOR}{sample}")
        if attribute is None:
            continue  # it varied only later, so the sample holds the mesh's own
        held = stored(layer)
        values = numpy.empty_like(held.values)
        attribute.data.foreach_get(held.prop, values)
        if held is not layer:  # a 2D vector stored as 3D
            values = values.reshape(-1, 3)[:, :2].ravel()
        copy.attributes[name].data.foreach_set(layer.prop, values)
    remove_samples(copy)
    return copy


def remove_samples(mesh: bpy.types.Mesh) -> None:
    """Remove every sample attribute `mesh` holds."""
    for name in [a.name for a in mesh.attributes if FRAME_SEPARATOR in a.name]:
        mesh.attributes.remove(mesh.attributes[name])
