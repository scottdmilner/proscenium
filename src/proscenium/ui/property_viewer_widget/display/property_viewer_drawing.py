"""Drawing a property viewer view into a host's layout: the properties as a virtualized UIList, and the selected one's.

A host's panel calls `draw_properties` or `draw_metadata` from its own `draw`, so the view draws wherever the host
puts it. The UIList's collection holds empty items, one per visible row; each row's content is read from the view's
list by its index, so only the row count crosses into RNA. The name column and the columns after it are drawn by
`property_columns`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy

from ... import search_box, text_wrapping, widget_updates
from ...columned_list import column_header, column_layout, column_settings
from ...widget_resources import badge_icons, keyframe_icons, list_keys, theme_colors
from ..property_list import property_descriptions
from . import prim_summary, property_columns, property_viewer_properties, property_viewer_views

if TYPE_CHECKING:
    from ..property_list import PropertyListView
    from .property_viewer_properties import PropertyViewerViewProperties

# The least width the name column keeps, in the header and in each row, however many columns show: in a region too
# narrow for it and the columns' widths, the columns shrink.
NAME_LEAST_UNITS = 4.0
# The list's rows before it's dragged taller, at most: it shows fewer when it holds fewer. Short, so a host's panels
# fit one above another, as a scene graph and a property viewer in one sidebar; it can be dragged to LIST_LEAST_ROWS.
LIST_ROWS = 10
LIST_LEAST_ROWS = 3
SETTINGS_CONTEXT_MEMBER = "proscenium_property_viewer_view"  # the view's properties, for the settings popover


def _name_column_factor(context: bpy.types.Context | None, properties: PropertyViewerViewProperties) -> float:
    """The name column's share of a row: all but the shown columns' widths, or NAME_LEAST_UNITS if more."""
    shown = column_layout.shown_columns(properties, property_columns.COLUMNS)
    columns_units = sum(column_layout.column_widths(context, properties, shown))
    return column_layout.leading_column_factor(context, columns_units, NAME_LEAST_UNITS)


class PropertyViewerList(bpy.types.UIList):
    """Draws a view's rows: each property, and under an expanded one its targets, in the header's columns.

    Its data is the view's properties, and its list ID is the view's name, so each view keeps its own scroll.
    """

    bl_idname = "PROSCENIUM_UL_property_viewer"

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
        view = property_viewer_views.find_view(data.name)
        property_list = view.property_list_view.live_list() if view is not None else None
        if layout is None or property_list is None or index is None or index >= len(property_list.rows):
            return
        row = property_list.rows[index]
        details = property_list.row_details(row)  # read once, when the row first comes on screen
        if details is None:
            return
        split = layout.split(factor=_name_column_factor(context, data))
        property_columns.draw_name_cell(split, data, property_list, index)
        shown = column_layout.shown_columns(data, property_columns.COLUMNS)
        cell = property_columns.PropertyCell(row, details, data.name, index)
        for cell_layout, column in zip(
            column_layout.column_cells(split.row(align=True), column_layout.column_widths(context, data, shown), shown),
            shown,
            strict=True,
        ):
            column.draw_cell(cell_layout, cell)

    @override
    def draw_filter(self, context: bpy.types.Context | None, layout: bpy.types.UILayout | None) -> None:
        # Nothing: the search, drawn below the list, filters the properties, and keeps a property's targets with it.
        return


class PropertyViewerSettings(bpy.types.Panel):
    """A view's settings, in a popover from the gear at its status line's end; drawn nowhere else."""

    bl_idname = "PROSCENIUM_PT_property_viewer_settings"
    bl_label = "Property Viewer Settings"
    bl_space_type = "TOPBAR"  # a header panel shows only where a popover opens it
    bl_region_type = "HEADER"

    @override
    def draw(self, context: bpy.types.Context | None) -> None:
        properties = getattr(context, SETTINGS_CONTEXT_MEMBER, None)
        layout = self.layout
        if properties is None or layout is None:
            return
        column_settings.draw_column_settings(layout, properties, property_columns.COLUMNS)


def _draw_header(
    layout: bpy.types.UILayout,
    context: bpy.types.Context,
    properties: PropertyViewerViewProperties,
    is_list_scrolling: bool,
) -> None:
    # A row above the list, split like the rows.
    split = column_header.header_row(layout, context, is_list_scrolling).split(
        factor=_name_column_factor(context, properties)
    )
    property_columns.draw_name_header(split)
    shown = column_layout.shown_columns(properties, property_columns.COLUMNS)  # chosen in the settings popover
    column_header.draw_column_titles(
        split.row(align=True), column_layout.column_widths(context, properties, shown), shown
    )


def _empty_text(property_list_view: PropertyListView) -> str:
    """What a view with no list says: why it has none."""
    if property_list_view.is_stage_expired():
        return "Stage closed"
    if property_list_view.stage() is None:
        return "No stage"
    if property_list_view.prim_path is None:
        return "No prim selected"
    return f"No prim at {property_list_view.prim_path}"


def draw_properties(
    layout: bpy.types.UILayout, context: bpy.types.Context, view_name: str, list_rows: int = LIST_ROWS
) -> None:
    """Draw a view's prim summary, header, properties, search box, and status, and watch its window's keys."""
    view = property_viewer_views.property_viewer_view(view_name)
    list_keys.ensure_watcher(context.window)
    properties = property_viewer_properties.view_properties(context.window_manager, view_name)
    if properties is None:
        layout.label(text="Loading")  # a file just loaded; its load handler makes the properties
        return
    property_list_view = view.property_list_view
    property_list = property_list_view.live_list()
    if property_list is None:
        layout.label(text=_empty_text(property_list_view))
        if property_list_view.property_list is not None:
            # A released stage or a recomposed prim; the stage timer reads it again and tells the host, as a draw
            # can't write the properties.
            widget_updates.schedule(view.run_stage_changes, 0.0)
        return
    theme_colors.read_theme_colors()  # the summary's badges and the rows' keyframes are drawn in its colors
    badge_icons.redraw_icons_if_theme_changed()
    keyframe_icons.redraw_icons_if_theme_changed()
    prim_summary.draw_summary(layout, context, view, property_list)
    header = layout.column()  # filled once the list has drawn, when its drawn rows tell whether it scrolls
    column_header.start_counting_rows(PropertyViewerList.bl_idname, view_name)
    layout.template_list(
        PropertyViewerList.bl_idname,
        view_name,
        properties,
        "rows",
        properties,
        "active_row_index",
        item_dyntip_propname="tooltip",
        rows=min(LIST_LEAST_ROWS, list_rows),  # the least it can be dragged to
        maxrows=list_rows,
    )
    is_list_scrolling = column_header.is_list_scrolling(
        PropertyViewerList.bl_idname, view_name, len(property_list.rows)
    )
    _draw_header(header, context, properties, is_list_scrolling)
    search_box.draw_search_box(
        layout, context, properties, "Search properties", toggles=(("search_authored_only", "GREASEPENCIL"),)
    )
    # The status below the search, which it reports on, with the settings gear at its end.
    status_row = layout.row()
    if property_list_view.search_error:
        status_row.label(text=property_list_view.search_error, icon="ERROR")
    else:
        status_row.label(
            text=property_descriptions.status_text(property_list.shown_property_count, property_list.property_count)
        )
    column_settings.draw_settings_gear(
        status_row, properties, PropertyViewerSettings.bl_idname, SETTINGS_CONTEXT_MEMBER
    )


def draw_metadata(layout: bpy.types.UILayout, context: bpy.types.Context, view_name: str) -> None:
    """Draw a summary of a view's selected property, wrapping a line too long for the region so its paths show whole."""
    property_list_view = property_viewer_views.property_viewer_view(view_name).property_list_view
    property_list = property_list_view.live_list()
    row = property_list_view.selected_row
    details = property_list.details(row.name) if property_list is not None and row is not None else None
    metadata = property_list.metadata(row.name) if property_list is not None and row is not None else None
    column = layout.column(align=True)
    column.scale_y = prim_summary.LINE_SCALE  # text lines, as close together as the prim summary's
    if row is None or details is None or metadata is None:
        column.label(text="Select a property")
        return
    for line in property_descriptions.metadata_lines(details, metadata, row):
        text_wrapping.draw_wrapped_label(column, context, line)


# In registration order.
CLASSES = (PropertyViewerList, PropertyViewerSettings)
