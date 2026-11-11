"""Drawing a scene graph view into a host's layout: the tree as a virtualized UIList, and the selected prim's details.

A host's panel calls `draw_tree` or `draw_details` from its own `draw`, so the view draws wherever the host puts
it. The UIList's collection holds empty items, one per visible row; each row's content is read from the view's tree
by its index, so only the row count crosses into RNA.
"""

from __future__ import annotations

from typing import Any, override

import bpy
from pxr import Kind

from ..prim_tree import prim_descriptions
from . import widget_keys, widget_operators, widget_properties, widget_views

# The columns after the name, in order: each view property that shows one, and its header.
COLUMNS = (("show_kind_column", "Kind"), ("show_type_column", "Type"))
# The share of a row the name column takes, in the header and in each row, by how many columns show after it.
NAME_COLUMN_FACTOR_BY_COLUMN_COUNT = {0: 0.85, 1: 0.72, 2: 0.56}
# Widths in UI units. A level holds its parent's guide line, under the center of that parent's chevron.
LEVEL_UNITS = 0.6
CHEVRON_UNITS = 0.6  # narrower than an icon button's 1.0, which leaves wide margins around the chevron
GUIDE_LINE_UNITS = 0.05
ROW_ICON_UNITS = 0.8  # the cell of the row's icon: its kind's, or else its type's
NAME_GAP_FACTOR = 1.0  # the separator between the icon and the name
LIST_ROWS = 16  # the list's starting height; it can be dragged taller

TYPE_ICONS = {
    "Xform": "EMPTY_AXIS",
    "Scope": "FILE_FOLDER",
    "Mesh": "MESH_DATA",
    "Camera": "CAMERA_DATA",
    "Material": "MATERIAL",
    "Shader": "NODE",
    "PointInstancer": "OUTLINER_OB_POINTCLOUD",
    "BasisCurves": "CURVE_DATA",
}


# Each model kind's icon, most derived first: an assembly is also a group. A kind registered as deriving from one of
# these takes its icon; any other kind takes OTHER_KIND_ICON.
KIND_ICONS = (
    (Kind.Tokens.assembly, "OUTLINER_OB_GROUP_INSTANCE"),
    (Kind.Tokens.group, "GROUP"),
    (Kind.Tokens.component, "MESH_CUBE"),
    (Kind.Tokens.subcomponent, "MOD_EXPLODE"),
)
OTHER_KIND_ICON = "BOOKMARKS"


def _type_icon(type_name: str) -> str:
    if type_name.endswith("Light"):
        return "LIGHT"
    return TYPE_ICONS.get(type_name, "DOT")


def _row_icon(details: Any) -> str:
    """A row's icon: a warning for an invalid model, its prim's kind's where it has a kind, or else its type's."""
    if details.is_invalid_model:
        return "ERROR"
    if not details.model_kind:
        return _type_icon(details.type_name)
    return next((icon for kind, icon in KIND_ICONS if Kind.Registry.IsA(details.model_kind, kind)), OTHER_KIND_ICON)


def _shown_columns(properties: Any) -> list[tuple[str, str]]:
    return [column for column in COLUMNS if getattr(properties, column[0])]


def _name_column_factor(properties: Any) -> float:
    return NAME_COLUMN_FACTOR_BY_COLUMN_COUNT[len(_shown_columns(properties))]


def _column_cells(layout: Any, column_count: int) -> list[Any]:
    """One right-aligned cell per shown column, sharing a layout's width evenly."""
    if column_count == 0:
        return []
    split = layout.split(factor=1 / column_count, align=True)
    cells = [split.row(align=True) for _ in range(column_count)]
    for cell in cells:
        cell.alignment = "RIGHT"
    return cells


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
        icon = _fixed_width(named, ROW_ICON_UNITS)
        icon.alert = details.is_invalid_model  # red, as the kind column's text is (ERROR keeps its own colors)
        icon.label(text="", icon=_row_icon(details))
        named.separator(factor=NAME_GAP_FACTOR)
        named.label(text=prim_descriptions.row_name(details, data.shown_name == "DISPLAY_NAME"))
        # The rows draw no badges for now; prim_descriptions.row_badges, badge_icons, and SceneGraphSelectRow
        # stay for when they're drawn again.
        column_texts = {"show_kind_column": details.model_kind, "show_type_column": details.type_name or "-"}
        shown = _shown_columns(data)
        for cell, (property_name, _) in zip(_column_cells(split.row(align=True), len(shown)), shown, strict=True):
            cell.alert = property_name == "show_kind_column" and details.is_invalid_model
            cell.label(text=column_texts[property_name])

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
    shown = _shown_columns(properties)
    cells = _column_cells(columns, len(shown))
    for cell, (property_name, title) in zip(cells, shown, strict=True):
        cell.label(text=title)
        cell.prop(properties, property_name, text="", icon="HIDE_OFF", emboss=False)
    # A hidden column's eye stays, after the shown ones, to show it again.
    hidden_eyes = cells[-1] if cells else columns
    if not cells:
        hidden_eyes.alignment = "RIGHT"
    for column in COLUMNS:
        if column not in shown:
            hidden_eyes.prop(properties, column[0], text="", icon="HIDE_ON", emboss=False)


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
    path = prim_tree_view.selected_path
    details = tree.details_at(path) if tree is not None and path else None
    prim_details = tree.prim_details(path) if tree is not None and path else None
    column = layout.column(align=True)
    if details is None or prim_details is None:
        column.label(text="Select a row")
        return
    for line in prim_descriptions.details_lines(details, prim_details):
        column.label(text=line)


# In registration order.
CLASSES = (SceneGraphList,)
