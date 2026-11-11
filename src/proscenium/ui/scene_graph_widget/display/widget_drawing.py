"""Drawing a scene graph view into a host's layout: the tree as a virtualized UIList, and the selected prim's details.

A host's panel calls `draw_tree` or `draw_details` from its own `draw`, so the view draws wherever the host puts
it. The UIList's collection holds empty items, one per visible row; each row's content is read from the view's tree
by its index, so only the row count crosses into RNA.
"""

from __future__ import annotations

from typing import Any, override

import bpy

from ..prim_tree import prim_descriptions
from . import badge_icons, widget_keys, widget_operators, widget_properties, widget_views

NAME_COLUMN_FACTOR = 0.72  # the share of a row the name column takes, in the header and in each row
NAME_COLUMN_FACTOR_WITHOUT_TYPE = 0.85
INDENT_FACTOR = 2.0  # separator factor per level
LIST_ROWS = 16  # the list's starting height; it can be dragged taller

TYPE_ICONS = {
    "Xform": "EMPTY_AXIS",
    "Scope": "OUTLINER_COLLECTION",
    "Mesh": "MESH_DATA",
    "Camera": "CAMERA_DATA",
    "Material": "MATERIAL",
    "Shader": "NODE",
    "PointInstancer": "OUTLINER_OB_POINTCLOUD",
    "BasisCurves": "CURVE_DATA",
}


def _type_icon(type_name: str) -> str:
    if type_name.endswith("Light"):
        return "LIGHT"
    return TYPE_ICONS.get(type_name, "DOT")


def _name_column_factor(properties: Any) -> float:
    return NAME_COLUMN_FACTOR if properties.show_type_column else NAME_COLUMN_FACTOR_WITHOUT_TYPE


class SceneGraphList(bpy.types.UIList):
    """Draws a view's rows as an indented tree with disclosure triangles, in the header's columns.

    Its data is the view's properties, and its list ID is the view's name, so each view keeps its own scroll.
    """

    bl_idname = "PROSCENIUM_UL_scene_graph"

    @override
    def draw_item(
        self,
        context: bpy.types.Context | None,
        layout: Any,
        data: Any,
        item: Any,
        icon: int | None,
        active_data: Any,
        active_property: str | None,
        index: int | None,
        flt_flag: int | None,
    ) -> None:
        view = widget_views.find_view(data.name)
        tree = view.prim_tree_view.live_tree() if view is not None else None
        if tree is None or index is None or index >= len(tree.rows):
            return
        tree_row = tree.rows[index]
        details = tree.details(tree_row)  # read once, when the row first comes on screen
        split = layout.split(factor=_name_column_factor(data))
        row = split.row(align=True)
        # Inactive prims, overs, classes, and rows that only hold search matches draw greyed.
        row.active = details.is_defined and tree.is_match(tree_row)
        # One small separator per level: a separator's spacer is square, so one deep one would make the row taller.
        for _ in range(tree_row.depth):
            row.separator(factor=INDENT_FACTOR)
        if details.has_children:
            disclosure = "DISCLOSURE_TRI_DOWN" if tree.is_expanded(tree_row) else "DISCLOSURE_TRI_RIGHT"
            toggle = row.operator(
                widget_operators.SceneGraphToggleRow.bl_idname, text="", icon=disclosure, emboss=False
            )
            toggle.view_name = data.name
            toggle.row_index = index
        else:
            row.label(text="", icon="BLANK1")
        row.label(text=details.name, icon=_type_icon(details.type_name))
        columns = split.row(align=True)
        columns.alignment = "RIGHT"
        for badge in prim_descriptions.row_badges(details):
            button = columns.operator(
                widget_operators.SceneGraphSelectRow.bl_idname,
                text="",
                icon_value=badge_icons.icon_id(badge),
                emboss=False,
            )
            button.view_name = data.name
            button.row_index = index
            button.badge = badge.value
        if data.show_type_column:
            columns.label(text=details.type_name or "-")

    @override
    def draw_filter(self, context: bpy.types.Context | None, layout: Any) -> None:
        # The list's own filter options (under its bottom triangle) hold the search's type and flags instead.
        wm: Any = context.window_manager if context is not None else None
        properties = widget_properties.view_properties(wm, self.list_id) if wm is not None else None
        if properties is None:
            return
        column = layout.column(align=True)
        column.prop(properties, "search_type_name", text="Type", icon="OUTLINER_DATA_EMPTY")
        flags = column.row(align=True)
        for property_name in widget_properties.FLAG_PROPERTY_NAMES.values():
            flags.prop(properties, property_name, toggle=True)


def _draw_header(layout: Any, properties: Any) -> None:
    # A row above the list, split like the rows; the list's own padding offsets its columns by a few pixels.
    split = layout.split(factor=_name_column_factor(properties))
    split.label(text="    Prim")
    columns = split.row(align=True)
    columns.alignment = "RIGHT"
    if properties.show_type_column:
        columns.label(text="Type")
    eye = "HIDE_OFF" if properties.show_type_column else "HIDE_ON"
    columns.prop(properties, "show_type_column", text="", icon=eye, emboss=False)


def draw_tree(layout: Any, context: Any, view_name: str, list_rows: int = LIST_ROWS) -> None:
    """Draw a view's search box, status, header, and tree into a layout, and watch its window's keys."""
    view = widget_views.scene_graph_view(view_name)
    widget_keys.ensure_watcher(context.window)
    properties = widget_properties.view_properties(context.window_manager, view_name)
    if properties is None:
        layout.label(text="Loading")  # a file just loaded; its load handler makes the properties
        return
    prim_tree_view = view.prim_tree_view
    tree = prim_tree_view.live_tree()
    if tree is None:
        layout.label(text="No stage" if prim_tree_view.tree is None else "Stage closed")
        return
    search = layout.row(align=True)
    search.prop(properties, "search_text", text="", icon="VIEWZOOM", placeholder="Search prims")
    search.prop(properties, "search_mode", text="")
    search.prop(properties, "search_case_sensitive", text="Aa", toggle=True)
    status = prim_tree_view.search_status
    layout.label(text=status.text or f"{len(tree.rows):,} visible rows", icon="ERROR" if status.is_error else "NONE")
    _draw_header(layout, properties)
    layout.template_list(
        SceneGraphList.bl_idname,
        view_name,
        properties,
        "rows",
        properties,
        "active_row_index",
        item_dyntip_propname="tooltip",
        rows=list_rows,
        maxrows=list_rows * 3,
    )


def draw_details(layout: Any, view_name: str) -> None:
    """Draw what a view's selected prim is."""
    prim_tree_view = widget_views.scene_graph_view(view_name).prim_tree_view
    tree = prim_tree_view.live_tree()
    stage = tree.stage() if tree is not None else None
    prim = stage.GetPrimAtPath(prim_tree_view.selected_path) if stage and prim_tree_view.selected_path else None
    column = layout.column(align=True)
    if not prim:
        column.label(text="Select a row")
        return
    for line in prim_descriptions.details_lines(prim):
        column.label(text=line)


# In registration order.
CLASSES = (SceneGraphList,)
