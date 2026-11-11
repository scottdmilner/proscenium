"""Drawing a scene graph view into a host's layout: the tree as a virtualized UIList, and the selected prim's details.

A host's panel calls `draw_tree` or `draw_details` from its own `draw`, so the view draws wherever the host puts
it. The UIList's collection holds empty items, one per visible row; each row's content is read from the view's tree
by its index, so only the row count crosses into RNA.
"""

from __future__ import annotations

from typing import Any, override

import bpy

from ..prim_tree import prim_descriptions
from . import widget_keys, widget_operators, widget_properties, widget_views

NAME_COLUMN_FACTOR = 0.72  # the share of a row the name column takes, in the header and in each row
NAME_COLUMN_FACTOR_WITHOUT_TYPE = 0.85
# Widths in UI units. A level holds its parent's guide line, under the center of that parent's chevron.
LEVEL_UNITS = 0.6
CHEVRON_UNITS = 0.6  # narrower than an icon button's 1.0, which leaves wide margins around the chevron
GUIDE_LINE_UNITS = 0.05
TYPE_ICON_UNITS = 0.8
NAME_GAP_FACTOR = 1.0  # the separator between the type icon and the name
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


def _fixed_width(layout: Any, width_units: float) -> Any:
    cell = layout.row(align=True)
    cell.ui_units_x = width_units
    return cell


def _draw_guide_level(layout: Any) -> None:
    """One indent level, with the vertical line that runs down from its open parent's chevron.

    Every ancestor of a visible row is expanded, so each level of a row's indent holds a line, and the lines join
    from row to row into one under each open chevron. A layout can't draw a vertical line, so it is a disabled button
    squeezed to a hairline: disabled, it draws faint, and a click on it selects the row.
    """
    level = _fixed_width(layout, LEVEL_UNITS)
    before_line = (CHEVRON_UNITS - GUIDE_LINE_UNITS) / 2
    _fixed_width(level, before_line).label(text="")
    line = _fixed_width(level, GUIDE_LINE_UNITS)
    line.enabled = False
    line.operator(widget_operators.SceneGraphGuideLine.bl_idname, text="", icon="BLANK1")
    # The parts have fixed widths that fill the level, so the line keeps its place whatever the row's alignment.
    _fixed_width(level, LEVEL_UNITS - before_line - GUIDE_LINE_UNITS).label(text="")


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
        for _ in range(tree_row.depth):
            _draw_guide_level(row)
        content = row.row(align=True)  # dimmed apart from the guide lines, so each line has one look down its length
        # Inactive prims and rows that only hold search matches draw greyed.
        content.active = details.is_active and tree.is_match(tree_row)
        chevron = _fixed_width(content, CHEVRON_UNITS)
        if details.has_children:
            disclosure = "DOWNARROW_HLT" if tree.is_expanded(tree_row) else "RIGHTARROW"  # chevrons, as the Outliner's
            toggle = chevron.operator(
                widget_operators.SceneGraphToggleRow.bl_idname, text="", icon=disclosure, emboss=False
            )
            toggle.view_name = data.name
            toggle.row_index = index
        else:
            chevron.label(text="", icon="BLANK1")
        # The icon in a cell of its own, and a separator before the name, set a narrower gap than a label's icon has.
        named = content.row(align=True)
        named.alert = details.is_orphaned_over  # red: nothing defines it, as a typo in an over's path leaves it
        _fixed_width(named, TYPE_ICON_UNITS).label(text="", icon=_type_icon(details.type_name))
        named.separator(factor=NAME_GAP_FACTOR)
        named.label(text=prim_descriptions.row_name(details, data.shown_name == "DISPLAY_NAME"))
        columns = split.row(align=True)
        columns.alignment = "RIGHT"
        # The rows draw no badges for now; prim_descriptions.row_badges, badge_icons, and SceneGraphSelectRow
        # stay for when they're drawn again.
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
    name_header = split.row()
    name_header.alignment = "LEFT"
    # A menu with an arrow after its text, so the header reads as clickable; an unembossed button shows no hover.
    # Under PULLDOWN_MENU the menu draws no arrow of its own, which would be dimmer than the text, so the arrow is a
    # character of the text, in its color.
    name_header.emboss = "PULLDOWN_MENU"
    title = "Display Name" if properties.shown_name == "DISPLAY_NAME" else "Prim"
    name_header.prop_menu_enum(properties, "shown_name", text=f"    {title} ⌄")
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
