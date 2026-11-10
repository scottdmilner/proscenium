"""The node-interface tree: Blender's C++ tree view, reached through a hidden custom node tree's interface.

Interface panels nest like prims (panels for prims with children, sockets for leaves), and
`template_node_tree_interface` draws them with Blender's own tree view. Built up front, up to a prim cap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy
import tree_model
from pxr import Sdf, Usd

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

NATIVE_TREE_NAME = ".poc_scene_graph"  # a leading dot hides the node group from ID browsers


class _NativeTreeState:
    """The interface-item paths and accessor for the open USD stage."""

    paths: dict[str, Sdf.Path] = {}  # interface item key (`item_key`) -> prim path
    stage: Callable[[], Usd.Stage | None] = lambda: None  # the open stage, as the add-on gives it


class POC_SG_NodeTree(bpy.types.NodeTree):  # noqa: N801 - Blender's class naming
    """A node tree type that exists only to hold the native tree's interface."""

    bl_idname = "PocSceneGraphTree"
    bl_label = "PoC Scene Graph"
    bl_icon = "OUTLINER"

    @override
    @classmethod
    def poll(cls, context: bpy.types.Context | None) -> bool:
        return False  # keeps it out of the node editor's tree type menu


def build(stage: Usd.Stage, cap: int) -> int:
    """Write the stage's hierarchy into the hidden node tree's interface, and return how many prims it holds."""
    node_groups: Any = bpy.data.node_groups  # the stubs only know Blender's own tree types
    node_tree = node_groups.get(NATIVE_TREE_NAME) or node_groups.new(NATIVE_TREE_NAME, POC_SG_NodeTree.bl_idname)
    interface: Any = node_tree.interface
    interface.clear()
    parents: dict[Sdf.Path, Any] = {}  # prim path -> its NodeTreeInterfacePanel
    _NativeTreeState.paths = {}
    built = 0
    for prim in _capped(Usd.PrimRange(stage.GetPseudoRoot(), tree_model.CHILD_PREDICATE), cap):
        if prim.IsPseudoRoot():
            continue
        parent = parents.get(prim.GetPath().GetParentPath())
        if tree_model.has_children(prim):
            item = interface.new_panel(prim.GetName(), default_closed=True)
            if parent is not None:
                interface.move_to_parent(item, parent, len(parent.interface_items))
            parents[prim.GetPath()] = item
        else:
            item = interface.new_socket(prim.GetName(), in_out="INPUT", socket_type="NodeSocketFloat", parent=parent)
        _NativeTreeState.paths[item_key(item)] = prim.GetPath()
        built += 1
    return built


def item_key(item: Any) -> str:
    """An interface item's identity, which survives the reordering that drag and drop and socket sorting do."""
    return f"panel:{item.persistent_uid}" if item.item_type == "PANEL" else f"socket:{item.identifier}"


def paths() -> dict[str, Sdf.Path]:
    """Each interface item's prim, by `item_key`."""
    return _NativeTreeState.paths


def active_path() -> Sdf.Path | None:
    """The prim of the tree's active item, if it has one."""
    node_tree = bpy.data.node_groups.get(NATIVE_TREE_NAME)
    active_item = node_tree.interface.active if node_tree else None
    return _NativeTreeState.paths.get(item_key(active_item)) if active_item else None


def _capped(prims: Iterable[Usd.Prim], cap: int) -> Iterable[Usd.Prim]:
    for count, prim in enumerate(prims):
        if count > cap:  # the pseudo-root is the first and isn't counted
            return
        yield prim


class POC_SG_OT_build_native(bpy.types.Operator):  # noqa: N801 - Blender's class naming
    """Build the node-interface tree from the stage, up to a number of prims."""

    bl_idname = "poc_sg.build_native"
    bl_label = "Build Native Tree"
    bl_options = {"INTERNAL"}

    cap: bpy.props.IntProperty(name="Prim Cap", default=2000, min=1)  # ty: ignore[invalid-type-form]

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        stage = _NativeTreeState.stage()
        if stage is None:
            return {"CANCELLED"}
        self.report({"INFO"}, f"Native tree: {build(stage, self.cap)} prims")
        return {"FINISHED"}


class POC_SG_PT_native(bpy.types.Panel):  # noqa: N801 - Blender's class naming
    """Blender's C++ tree view, through the hidden node tree's interface."""

    bl_idname = "POC_SG_PT_native"
    bl_label = "Scene Graph (Native Tree)"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "USD Tree"
    bl_options = {"DEFAULT_CLOSED"}

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout  # never None while drawing
        layout.operator(POC_SG_OT_build_native.bl_idname, icon="FILE_REFRESH")
        node_tree = bpy.data.node_groups.get(NATIVE_TREE_NAME)
        if node_tree is not None:
            layout.template_node_tree_interface(node_tree.interface)


CLASSES = (POC_SG_NodeTree, POC_SG_OT_build_native, POC_SG_PT_native)


def register(stage: Callable[[], Usd.Stage | None]) -> None:
    """Register the native tree's classes; stage gives the open stage when the tree is built."""
    _NativeTreeState.stage = stage
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    """Undo `register`."""
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    _NativeTreeState.paths = {}


def reset() -> None:
    """Forget the item-to-prim map, as when a new stage opens."""
    _NativeTreeState.paths = {}
