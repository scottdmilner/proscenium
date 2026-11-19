"""The cook's tree as a USD layer, written from a Blender node tree (docs/phase3/node-tree.md "The tree as plain data").

`/Tree` is a `NodeTree` with `int tree:format`, and each of the cook's nodes is a child prim named for its node ID,
the Blender node's name, as the cook encodes it. Every node authors its `node:version`, `node:mute` only when muted,
a connection per link, each input or property whose value isn't its definition's default, and its outputs. A begin
names its end with `rel zone:end`. Reroutes are stripped, so a link through them names the node they start from, and
frames and muted links are left out. Which Viewer is active isn't in the tree: it's the cook's argument.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pxr import Sdf

import proscenium_cook

from . import cook_node_types

if TYPE_CHECKING:
    from collections.abc import Iterator

    import bpy

TREE_FORMAT = 1
TREE_PATH = Sdf.Path("/Tree")


def write_tree_layer(tree: bpy.types.NodeTree, layer: Sdf.Layer) -> None:
    """Author tree into layer, which should be empty."""
    root = Sdf.PrimSpec(layer, TREE_PATH.name, Sdf.SpecifierDef, "NodeTree")
    tree_format = Sdf.AttributeSpec(root, "tree:format", Sdf.ValueTypeNames.Int)
    tree_format.default = TREE_FORMAT
    for node in tree.nodes:
        if isinstance(node, cook_node_types.CookNode):
            _write_node(tree, node, root)


def node_prim_path(node_name: str) -> Sdf.Path:
    """The path of the prim that stands for the node named node_name."""
    return TREE_PATH.AppendChild(proscenium_cook.prim_name_from_node_id(node_name))


def _write_node(tree: bpy.types.NodeTree, node: Any, root: Sdf.PrimSpec) -> None:
    definition: cook_node_types.CookNodeDefinition = node.cook_definition
    prim = Sdf.PrimSpec(root, node_prim_path(node.name).name, Sdf.SpecifierDef, definition.type_name)
    Sdf.AttributeSpec(prim, "node:version", Sdf.ValueTypeNames.Int).default = definition.node_version
    if node.mute:
        Sdf.AttributeSpec(prim, "node:mute", Sdf.ValueTypeNames.Bool).default = True
    sockets_by_namespace = {"inputs": node.inputs, "outputs": node.outputs}
    for attribute in definition.attributes:
        if attribute.namespace == "props":
            if cook_node_types.is_editable_value(attribute) and hasattr(node, attribute.property_name):
                _write_value(prim, attribute, getattr(node, attribute.property_name))
            continue
        socket = _socket(sockets_by_namespace[attribute.namespace], attribute.base_name)
        if attribute.namespace == "outputs":
            Sdf.AttributeSpec(prim, attribute.attribute_name, attribute.value_type)
            continue
        upstream = list(_upstream_outputs(socket)) if socket is not None else []
        if upstream:
            spec = Sdf.AttributeSpec(prim, attribute.attribute_name, attribute.value_type)
            spec.connectionPathList.explicitItems = [
                node_prim_path(name).AppendProperty(f"outputs:{identifier}") for name, identifier in upstream
            ]
        elif socket is not None and cook_node_types.is_editable_value(attribute) and hasattr(socket, "default_value"):
            _write_value(prim, attribute, socket.default_value)
    if definition.zone_role == "begin":
        end_name = getattr(node, cook_node_types.ZONE_END_PROPERTY)
        if end_name and end_name in tree.nodes:
            relationship = Sdf.RelationshipSpec(prim, "zone:end", custom=False)
            relationship.targetPathList.explicitItems = [node_prim_path(end_name)]


def _write_value(prim: Sdf.PrimSpec, attribute: cook_node_types.CookAttribute, value: Any) -> None:
    """Author value, unless it's the definition's default, which the cook reads for an unauthored one."""
    if cook_node_types.is_vector(attribute):
        value = tuple(value)
        default = tuple(attribute.default) if attribute.default is not None else None
    else:
        default = attribute.default
    if value == default:
        return
    Sdf.AttributeSpec(prim, attribute.attribute_name, attribute.value_type).default = value


def _socket(sockets: Any, identifier: str) -> Any:
    return next((socket for socket in sockets if socket.identifier == identifier), None)


def _upstream_outputs(socket: Any) -> Iterator[tuple[str, str]]:
    """(node name, output identifier) for each link into socket, in Blender's multi-input order, past reroutes."""
    links = [link for link in socket.links if not link.is_muted]
    if socket.is_multi_input:
        links.sort(key=lambda link: link.multi_input_sort_id)
    for link in links:
        for node, output in cook_node_types.link_origins(link):
            yield node.name, output.identifier
