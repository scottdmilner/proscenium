"""Drawing a scene graph view into a host's layout: the tree as a virtualized UIList, and the selected prim's details.

A host's panel calls `draw_tree` or `draw_details` from its own `draw`, so the view draws wherever the host puts
it. The UIList's collection holds empty items, one per visible row; each row's content is read from the view's tree
by its index, so only the row count crosses into RNA. Each column's cells are drawn by its module in `list_columns/`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy

from ... import search_box, widget_updates
from ...columned_list import column_header, column_layout, column_settings
from ...widget_resources import list_keys
from ..prim_tree import prim_descriptions
from . import scene_graph_properties, scene_graph_views
from .list_columns import COLUMNS, name_column, redraw_icons_if_theme_changed

if TYPE_CHECKING:
    from .scene_graph_properties import SceneGraphViewProperties

# The least width the name column keeps, in the header and in each row, however many columns show: in a region too
# narrow for it and the columns' widths, the columns shrink. Enough for a row a few levels deep to keep its icon and
# the first letters of its name.
NAME_LEAST_UNITS = 5.0
# The list's rows before it's dragged taller, at most: it shows fewer when it holds fewer. Short, so a host's panels
# fit one above another, as a scene graph and a property viewer in one sidebar; it can be dragged to LIST_LEAST_ROWS.
LIST_ROWS = 10
LIST_LEAST_ROWS = 3
SETTINGS_CONTEXT_MEMBER = "proscenium_scene_graph_view"  # the view's properties, for the settings popover


def _name_column_factor(context: bpy.types.Context | None, properties: SceneGraphViewProperties) -> float:
    """The name column's share of a row: all but the shown columns' widths, or NAME_LEAST_UNITS if more."""
    shown = column_layout.shown_columns(properties, COLUMNS)
    columns_units = sum(column_layout.column_widths(context, properties, shown))
    return column_layout.leading_column_factor(context, columns_units, NAME_LEAST_UNITS)


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
        column_header.count_drawn_row(self.bl_idname, data.name)
        view = scene_graph_views.find_view(data.name)
        tree = view.prim_tree_view.live_tree() if view is not None else None
        if layout is None or tree is None or index is None or index >= len(tree.rows):
            return
        details = tree.details(tree.rows[index])  # read once, when the row first comes on screen
        split = layout.split(factor=_name_column_factor(context, data))
        name_column.draw_name_cell(split, data, tree, index, details)
        shown = column_layout.shown_columns(data, COLUMNS)
        widths_units = column_layout.column_widths(context, data, shown)
        for cell, column in zip(
            column_layout.column_cells(split.row(align=True), widths_units, shown), shown, strict=True
        ):
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
        column_settings.draw_column_settings(layout, properties, COLUMNS)


def _draw_header(
    layout: bpy.types.UILayout,
    context: bpy.types.Context,
    properties: SceneGraphViewProperties,
    is_list_scrolling: bool,
) -> None:
    # A row above the list, split like the rows.
    split = column_header.header_row(layout, context, is_list_scrolling).split(
        factor=_name_column_factor(context, properties)
    )
    name_column.draw_name_header(split, properties)
    shown = column_layout.shown_columns(properties, COLUMNS)  # chosen in the settings popover
    column_header.draw_column_titles(
        split.row(align=True), column_layout.column_widths(context, properties, shown), shown
    )


def draw_tree(
    layout: bpy.types.UILayout, context: bpy.types.Context, view_name: str, list_rows: int = LIST_ROWS
) -> None:
    """Draw a view's status, header, tree, and search box below it, and watch its window's keys."""
    view = scene_graph_views.scene_graph_view(view_name)
    list_keys.ensure_watcher(context.window)
    properties = scene_graph_properties.view_properties(context.window_manager, view_name)
    if properties is None:
        layout.label(text="Loading")  # a file just loaded; its load handler makes the properties
        return
    prim_tree_view = view.prim_tree_view
    tree = prim_tree_view.live_tree()
    if tree is None:
        layout.label(text="No stage" if prim_tree_view.tree is None else "Stage closed")
        if prim_tree_view.selected_path is not None:
            # A released stage sends no notice; the stage timer drops its selection and tells the host, as a draw
            # can't write the properties.
            widget_updates.schedule(view.run_stage_changes, 0.0)
        return
    status = prim_tree_view.search_status
    status_row = layout.row()
    status_row.label(
        text=status.text or f"{len(tree.rows):,} visible rows", icon="ERROR" if status.is_error else "NONE"
    )
    column_settings.draw_settings_gear(status_row, properties, SceneGraphSettings.bl_idname, SETTINGS_CONTEXT_MEMBER)
    header = layout.column()  # filled once the list has drawn, when its drawn rows tell whether it scrolls
    redraw_icons_if_theme_changed()
    column_header.start_counting_rows(SceneGraphList.bl_idname, view_name)
    layout.template_list(
        SceneGraphList.bl_idname,
        view_name,
        properties,
        "rows",
        properties,
        "active_row_index",
        item_dyntip_propname="tooltip",
        rows=min(LIST_LEAST_ROWS, list_rows),  # the least it can be dragged to
        maxrows=list_rows,
    )
    is_list_scrolling = column_header.is_list_scrolling(SceneGraphList.bl_idname, view_name, len(tree.rows))
    _draw_header(header, context, properties, is_list_scrolling)
    search_box.draw_search_box(
        layout, context, properties, "Search prims", toggles=(("search_shown_rows_only", "FILTER"),)
    )


def draw_details(layout: bpy.types.UILayout, view_name: str) -> None:
    """Draw what a view's selected prim is."""
    prim_tree_view = scene_graph_views.scene_graph_view(view_name).prim_tree_view
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
