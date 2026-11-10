"""Caches of whole meshes, for a cached display's meshes whose topology varies (M4 Phase E, E4).

A mesh's own attributes can't hold another topology, so each sample of such a mesh is a whole mesh, which its
objects show through a Geometry Nodes modifier in place of their own: a mesh per sample (MeshSamples), each on a
holder object in a collection of the mesh's samples, which no scene links. A copy's modifier shows the geometry
of the holder its `Sample` input names, keyed like the attribute caches' (cached_display.py), so it shows at each time
the latest sample at or before it; no sample blends with the next.
"""

from __future__ import annotations

from typing import Any

import bpy

SAMPLE, SAMPLES = "Sample", "Samples"
# The copies' group's inputs after the geometry; cached_display.py keys Sample through Socket_1, as for attributes.
INPUTS = {SAMPLE: "Socket_1", SAMPLES: "Socket_2"}
HOLDER_PREFIX = "proscenium holder "
_holders: int | None = None  # the latest holder's number, so a collection's children sort in the order they came


def _holder(mesh: bpy.types.Mesh | None) -> bpy.types.Object:
    """A hidden object no scene links, named in the order holders are made."""
    global _holders  # noqa: PLW0603 - a process-wide count, so names never collide
    if _holders is None:  # after any holder the file already has, as Blender would rename a colliding one
        numbers = [o.name.removeprefix(HOLDER_PREFIX)[:8] for o in bpy.data.objects if o.name.startswith(HOLDER_PREFIX)]
        _holders = max((int(n) for n in numbers if n.isdigit()), default=0)
    _holders += 1
    holder = bpy.data.objects.new(f"{HOLDER_PREFIX}{_holders:08d}", mesh)
    holder.hide_viewport = holder.hide_render = True
    return holder


class MeshSamples:
    """A mesh per sample, each on a holder in the collection a copy's modifier shows one object of.

    The parts of a split mesh share it: each part's keys name only the samples it added.
    """

    collection: bpy.types.Collection

    def __init__(self, name: str) -> None:
        self.collection = bpy.data.collections.new(f"{name} samples")

    def add(self, mesh: bpy.types.Mesh) -> int:
        """Add `mesh` as a sample; its index, to key."""
        # Collection Children gives a collection's objects in name order, the order holders were made.
        self.collection.objects.link(_holder(mesh))
        return len(self.collection.objects) - 1

    def show(self, modifier: Any, group: bpy.types.NodeTree) -> None:
        """Have a copy's modifier show these samples through `group`, samples_group()."""
        if modifier.node_group != group:
            modifier.node_group = group
        getattr(modifier.properties.inputs, INPUTS[SAMPLES]).value = self.collection

    def datablocks(self) -> list[bpy.types.ID]:
        holders = list(self.collection.objects)
        return [self.collection, *holders, *(h.data for h in holders if h.data is not None)]


def samples_group() -> bpy.types.NodeTree:
    """A copy's group for MeshSamples: the geometry of the object of `Samples` that `Sample` names.

    It shares the holder's mesh rather than copying it, in place of the copy's own geometry.
    """
    tree: Any = bpy.data.node_groups.new("Proscenium samples", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    _input(tree, SAMPLE, "NodeSocketInt")
    _input(tree, SAMPLES, "NodeSocketCollection")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = tree.nodes, tree.links
    group_input = nodes.new("NodeGroupInput")
    children = nodes.new("GeometryNodeCollectionChildren")  # its objects, in name order
    links.new(group_input.outputs[SAMPLES], children.inputs["Collection"])
    item = nodes.new("GeometryNodeListGetItem")
    item.socket_type = "OBJECT"
    links.new(children.outputs["Objects"], item.inputs["List"])
    links.new(group_input.outputs[SAMPLE], item.inputs["Index"])
    info = nodes.new("GeometryNodeObjectInfo")
    info.transform_space = "ORIGINAL"
    links.new(item.outputs["Value"], info.inputs["Object"])
    links.new(info.outputs["Geometry"], nodes.new("NodeGroupOutput").inputs[0])
    return tree


def _input(tree: Any, name: str, socket_type: str) -> None:
    socket = tree.interface.new_socket(name, in_out="INPUT", socket_type=socket_type)
    if socket.identifier != INPUTS[name]:  # the modifier's inputs are set through it
        raise RuntimeError(f"Expected input {name} to be {INPUTS[name]}, not {socket.identifier}")
