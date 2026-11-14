"""The buttons a property row draws of its own: the disclosure triangle, and a target's jump button.

The triangle shows or hides a property's targets; the jump button asks the host to select a target where it shows it,
as in a scene graph.

Its guide line's button and its copy-path button are the shared `tree_rows.TreeGuideLine` and
`clipboard_operators.CopyUsdPath`. It's internal: expansion in a list is view state, so it pushes no undo step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy

from ..property_list import property_descriptions
from . import property_viewer_properties, property_viewer_views

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

    from ..property_list import PropertyList, PropertyRow


def _list(view_name: str) -> PropertyList | None:
    """A view's list, if the view exists and its prim is alive."""
    view = property_viewer_views.find_view(view_name)
    return view.property_list_view.live_list() if view is not None else None


def _row(view_name: str, row_index: int) -> PropertyRow | None:
    """A view's row, if the view exists and has it."""
    property_list = _list(view_name)
    if property_list is None or not 0 <= row_index < len(property_list.rows):
        return None
    return property_list.rows[row_index]


class PropertyViewerToggleRow(bpy.types.Operator):
    """Show or hide a property's targets (Shift: every property's)."""

    bl_idname = "proscenium.property_viewer_toggle_row"
    bl_label = "Toggle Targets"
    bl_options = {"INTERNAL"}

    view_name: bpy.props.StringProperty()  # ty: ignore[invalid-type-form]
    row_index: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]
    every_property: bpy.props.BoolProperty()  # ty: ignore[invalid-type-form]

    @override
    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        # The tooltip, asked for each triangle as it is hovered; properties are that button's own.
        property_list = _list(properties.view_name)
        row = _row(properties.view_name, properties.row_index)
        details = property_list.row_details(row) if property_list is not None and row is not None else None
        if property_list is None or row is None or details is None:
            return ""
        return property_descriptions.disclosure_tooltip(details, property_list.is_expanded(row.name))

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        self.every_property = event.shift
        return self.execute(context)

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        if _row(self.view_name, self.row_index) is None:
            return {"CANCELLED"}
        property_viewer_views.set_entering_search_text(self.view_name, is_entering=False)  # a click ends typing
        view = property_viewer_views.property_viewer_view(self.view_name)
        before = view.property_list_view.selected_path
        view.property_list_view.toggle_row(self.row_index, self.every_property)
        property_viewer_properties.sync_and_notify(view, before)
        return {"FINISHED"}


class PropertyViewerJumpToTarget(bpy.types.Operator):
    """Select a target where the property viewer's host shows it, as in a scene graph."""

    bl_idname = "proscenium.property_viewer_jump_to_target"
    bl_label = "Jump to Target"
    bl_options = {"INTERNAL"}

    view_name: bpy.props.StringProperty()  # ty: ignore[invalid-type-form]
    row_index: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]

    @override
    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        property_list = _list(properties.view_name)
        row = _row(properties.view_name, properties.row_index)
        details = property_list.row_details(row) if property_list is not None and row is not None else None
        if row is None or row.target_path is None or details is None:
            return ""
        is_missing = property_descriptions.is_target_missing(details, row)
        return property_descriptions.jump_tooltip(row.target_path, is_missing)

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        view = property_viewer_views.find_view(self.view_name)
        property_list = _list(self.view_name)
        row = _row(self.view_name, self.row_index)
        details = property_list.row_details(row) if property_list is not None and row is not None else None
        if view is None or view.on_jump_to_target is None or row is None or row.target_path is None:
            return {"CANCELLED"}
        if details is None or property_descriptions.is_target_missing(details, row):
            return {"CANCELLED"}  # nothing on the stage to select
        property_viewer_views.set_entering_search_text(self.view_name, is_entering=False)  # a click ends typing
        view.on_jump_to_target(row.target_path)
        return {"FINISHED"}


# In registration order.
CLASSES = (PropertyViewerToggleRow, PropertyViewerJumpToTarget)
