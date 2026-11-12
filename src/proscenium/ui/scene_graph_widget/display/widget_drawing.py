"""Drawing a scene graph view into a host's layout: the tree as a virtualized UIList, and the selected prim's details.

A host's panel calls `draw_tree` or `draw_details` from its own `draw`, so the view draws wherever the host puts
it. The UIList's collection holds empty items, one per visible row; each row's content is read from the view's tree
by its index, so only the row count crosses into RNA. Each column's cells are drawn by its module in `list_columns/`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy

from ..prim_tree import prim_descriptions
from . import widget_keys, widget_properties, widget_views
from .list_columns import COLUMNS, column_layout, name_column, redraw_icons_if_theme_changed

if TYPE_CHECKING:
    from .widget_properties import SceneGraphViewProperties

# The least width the name column keeps, in the header and in each row, however many columns show: in a region too
# narrow for it and the columns' widths, the columns shrink. Enough for a row a few levels deep to keep its icon and
# the first letters of its name.
NAME_LEAST_UNITS = 5.0
# Each view's rows drawn in the current draw of its list: the list draws only the rows on screen, so fewer than the
# tree's means it scrolls, which Python can't otherwise read.
_drawn_row_counts: dict[str, int] = {}
LIST_ROWS = 16  # the list's starting height; it can be dragged taller
# What a scrolling list's scrollbar takes from its rows' width, the gap before it included: the header leaves it
# blank, so its columns stay over the rows'.
SCROLLBAR_UNITS = 0.5
SEARCH_MODE_UNITS = 6.0  # the search's match dropdown, wide enough for its longest mode, "Path contains"
SEARCH_TOGGLE_UNITS = 1.0  # each toggle after it, an icon button's width
SEARCH_TEXT_LEAST_FACTOR = 0.4  # the text field's share of the search row in a region too narrow for the rest
SETTINGS_CONTEXT_MEMBER = "proscenium_scene_graph_view"  # the view's properties, for the settings popover


def _shown_columns(properties: SceneGraphViewProperties) -> list[column_layout.Column]:
    return [column for column in COLUMNS if getattr(properties, column.show_property)]


def _name_column_factor(context: bpy.types.Context | None, properties: SceneGraphViewProperties) -> float:
    """The name column's share of a row: all but the shown columns' widths, or NAME_LEAST_UNITS if more."""
    columns_units = sum(column_layout.column_units(properties, column) for column in _shown_columns(properties))
    if columns_units == 0:
        return 1.0
    row_units = column_layout.row_units(context)
    if row_units is None:  # no region's width to read: the name and the columns share it as their least widths do
        return NAME_LEAST_UNITS / (NAME_LEAST_UNITS + columns_units)
    return min(1.0, max(NAME_LEAST_UNITS, row_units - columns_units) / row_units)


class SceneGraphList(bpy.types.UIList):
    """Draws a view's rows as an indented tree with disclosure triangles, in the header's columns.

    Its data is the view's properties, and its list ID is the view's name, so each view keeps its own scroll.
    """

    bl_idname = "PROSCENIUM_UL_scene_graph"

    @override
    def draw_item(
        self,
        context: bpy.types.Context | None,
        layout: bpy.types.UILayout | None,
        data: Any,
        item: Any,
        icon: int | None,
        active_data: Any,
        active_property: str | None,
        index: int | None,
        flt_flag: int | None,
    ) -> None:
        _drawn_row_counts[data.name] = _drawn_row_counts.get(data.name, 0) + 1
        view = widget_views.find_view(data.name)
        tree = view.prim_tree_view.live_tree() if view is not None else None
        if layout is None or tree is None or index is None or index >= len(tree.rows):
            return
        details = tree.details(tree.rows[index])  # read once, when the row first comes on screen
        split = layout.split(factor=_name_column_factor(context, data))
        name_column.draw_name_cell(split, data, tree, index, details)
        shown = _shown_columns(data)
        for cell, column in zip(column_layout.column_cells(split.row(align=True), data, shown), shown, strict=True):
            column.draw_cell(cell, details)

    @override
    def draw_filter(self, context: bpy.types.Context | None, layout: bpy.types.UILayout | None) -> None:
        # Nothing: the list's own name filter would hide rows without keeping their ancestors, and the search,
        # drawn below the list, does that. A text field drawn here lost its arrow keys to the key watcher.
        return


class SceneGraphSettings(bpy.types.Panel):
    """A view's settings, in a popover from the gear at its status line's end; drawn nowhere else."""

    bl_idname = "PROSCENIUM_PT_scene_graph_settings"
    bl_label = "Scene Graph Settings"
    bl_space_type = "TOPBAR"  # a header panel shows only where a popover opens it
    bl_region_type = "HEADER"

    @override
    def draw(self, context: bpy.types.Context | None) -> None:
        properties = getattr(context, SETTINGS_CONTEXT_MEMBER, None)
        layout = self.layout
        if properties is None or layout is None:
            return
        layout.label(text="Columns")
        for column in COLUMNS:
            row = layout.row()
            is_shown = getattr(properties, column.show_property)
            # The eye, open or closed, as the Outliner's; then the title, and the width, dimmed while hidden, for a
            # column that has one.
            eye_and_title = row.row(align=True)
            eye_and_title.prop(
                properties, column.show_property, text="", icon="HIDE_OFF" if is_shown else "HIDE_ON", emboss=False
            )
            eye_and_title.label(text=column.title)
            width = row.row()
            width.active = is_shown
            if column.units_property:
                width.prop(properties, column.units_property)
            else:
                width.label(text="")


def _draw_search(layout: bpy.types.UILayout, context: bpy.types.Context, properties: SceneGraphViewProperties) -> None:
    # The text field takes what the mode and toggles leave; in a row, every item would grow with the width.
    options_units = SEARCH_MODE_UNITS + 2 * SEARCH_TOGGLE_UNITS
    text_factor = column_layout.split_factor_leaving(context, options_units, SEARCH_TEXT_LEAST_FACTOR)
    split = layout.split(factor=text_factor, align=True)
    split.row(align=True).prop(properties, "search_text", text="", icon="VIEWZOOM", placeholder="Search prims")
    options = split.row(align=True)
    options.prop(properties, "search_mode", text="")
    # As wide as the icon-only toggle after it.
    column_layout.fixed_width(options, SEARCH_TOGGLE_UNITS).prop(
        properties, "search_case_sensitive", text="Aa", toggle=True
    )
    column_layout.fixed_width(options, SEARCH_TOGGLE_UNITS).prop(
        properties, "search_shown_rows_only", text="", icon="FILTER", toggle=True
    )


def _draw_header(
    layout: bpy.types.UILayout,
    context: bpy.types.Context,
    properties: SceneGraphViewProperties,
    is_list_scrolling: bool,
) -> None:
    # A row above the list, split like the rows; the list's own padding offsets its columns by a few pixels. A
    # scrolling list's rows are narrower by its scrollbar, so the header leaves the scrollbar's width blank and splits
    # the rest as they split theirs.
    if is_list_scrolling:
        scrollbar_split = layout.split(factor=column_layout.split_factor_leaving(context, SCROLLBAR_UNITS, 0.0))
        layout = scrollbar_split.row()
        scrollbar_split.label(text="")
    split = layout.split(factor=_name_column_factor(context, properties))
    name_column.draw_name_header(split, properties)
    shown = _shown_columns(properties)  # chosen in the settings popover
    for cell, column in zip(column_layout.column_cells(split.row(align=True), properties, shown), shown, strict=True):
        if column.header_icon:
            cell.label(text="", icon=column.header_icon)
        else:
            cell.label(text=column.title)


def draw_tree(
    layout: bpy.types.UILayout, context: bpy.types.Context, view_name: str, list_rows: int = LIST_ROWS
) -> None:
    """Draw a view's status, header, tree, and search box below it, and watch its window's keys."""
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
    status = prim_tree_view.search_status
    status_row = layout.row()
    status_row.label(
        text=status.text or f"{len(tree.rows):,} visible rows", icon="ERROR" if status.is_error else "NONE"
    )
    # The view's settings at the status line's end; the popover reads the view's properties from the context set here.
    settings = status_row.row()
    settings.alignment = "RIGHT"
    settings.emboss = "NONE"
    settings.context_pointer_set(SETTINGS_CONTEXT_MEMBER, properties)
    settings.popover(SceneGraphSettings.bl_idname, text="", icon="PREFERENCES")
    header = layout.column()  # filled once the list has drawn, when its drawn rows tell whether it scrolls
    redraw_icons_if_theme_changed()
    _drawn_row_counts[view_name] = 0
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
    _draw_header(header, context, properties, _drawn_row_counts.pop(view_name, 0) < len(tree.rows))
    _draw_search(layout, context, properties)


def draw_details(layout: bpy.types.UILayout, view_name: str) -> None:
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
CLASSES = (SceneGraphList, SceneGraphSettings)
