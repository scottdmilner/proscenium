"""The buttons a scene graph row draws: its disclosure triangle and its badges.

Both are internal operators: expansion and selection in a tree are view state, so they push no undo step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy

from ..prim_tree import prim_descriptions
from . import widget_properties, widget_views

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

    from ..prim_tree import PrimTree, TreeRow


def _tree(view_name: str) -> PrimTree | None:
    """A view's tree, if the view exists and its stage is alive."""
    view = widget_views.find_view(view_name)
    return view.prim_tree_view.live_tree() if view is not None else None


def _row(view_name: str, row_index: int) -> TreeRow | None:
    """A view's row, if the view exists and has it."""
    tree = _tree(view_name)
    return tree.rows[row_index] if tree is not None and 0 <= row_index < len(tree.rows) else None


class SceneGraphToggleRow(bpy.types.Operator):
    """Expand or collapse a prim (Shift: its whole subtree)."""

    bl_idname = "proscenium.scene_graph_toggle_row"
    bl_label = "Toggle Prim"
    bl_options = {"INTERNAL"}

    view_name: bpy.props.StringProperty()  # ty: ignore[invalid-type-form]
    row_index: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]
    recursive: bpy.props.BoolProperty()  # ty: ignore[invalid-type-form]

    @override
    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        # The tooltip, asked for each triangle as it is hovered; properties are that button's own.
        tree = _tree(properties.view_name)
        row = _row(properties.view_name, properties.row_index)
        if tree is None or row is None:
            return ""
        return prim_descriptions.disclosure_tooltip(row.prim, tree.is_expanded(row))

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        self.recursive = event.shift
        return self.execute(context)

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        if _row(self.view_name, self.row_index) is None:
            return {"CANCELLED"}
        widget_views.scene_graph_view(self.view_name).prim_tree_view.toggle_row(self.row_index, self.recursive)
        widget_properties.sync_rows(self.view_name)
        return {"FINISHED"}


class SceneGraphSelectRow(bpy.types.Operator):
    """Select the row a badge is on."""

    bl_idname = "proscenium.scene_graph_select_row"
    bl_label = "Select Prim"
    bl_options = {"INTERNAL"}

    view_name: bpy.props.StringProperty()  # ty: ignore[invalid-type-form]
    row_index: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]
    badge: bpy.props.StringProperty()  # ty: ignore[invalid-type-form]  # a prim_descriptions.Badge value

    @override
    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        # Labels can't have tooltips, so a badge is this operator's borderless button, and this is its tooltip.
        row = _row(properties.view_name, properties.row_index)
        if row is None or properties.badge not in {badge.value for badge in prim_descriptions.Badge}:
            return ""
        return prim_descriptions.badge_tooltip(row.prim, prim_descriptions.Badge(properties.badge))

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        if _row(self.view_name, self.row_index) is None:
            return {"CANCELLED"}
        view = widget_views.scene_graph_view(self.view_name)
        before = view.prim_tree_view.selected_path
        view.prim_tree_view.select_row(self.row_index)
        widget_properties.sync_and_notify(view, before)
        return {"FINISHED"}


# In registration order.
CLASSES = (SceneGraphToggleRow, SceneGraphSelectRow)
