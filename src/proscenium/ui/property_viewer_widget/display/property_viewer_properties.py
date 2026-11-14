"""The properties a property viewer view is drawn from, and keeping them in step with the view's list.

Each view's properties are an item of the window manager's `proscenium_property_viewer_views` collection, named for
the view: one empty row item per visible row, the active row, the search fields, and the column settings. The window
manager's properties aren't saved, and loading a file replaces them, so the items are made again after each load.
Everything that reads or writes these properties is here, with their update callbacks.

The view is what owns its state; the properties mirror it. The search fields are the one exception, the query being
edited: a pause after they last change, `apply_pending` applies them to the view, whose `query` is then the applied
one. Properties made for an existing view, as after a load, start from its applied query.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import bpy

from ... import search_box, widget_updates
from ...widget_model import text_matching
from ...widget_resources import list_keys
from ..property_list import property_descriptions, property_search
from . import property_viewer_views

if TYPE_CHECKING:
    from pxr import Sdf

VIEWS_PROPERTY = "proscenium_property_viewer_views"  # the WindowManager's collection of PropertyViewerViewProperties
SEARCH_DELAY_SECONDS = 0.25  # after the last keystroke, before a search runs
# A row item's RNA path: "proscenium_property_viewer_views[<view index>].rows[<row index>]".
_ROW_ITEM_PATH = re.compile(rf"{VIEWS_PROPERTY}\[(\d+)\]\.rows\[(\d+)\]$")


def _row_tooltip(row_item: Any) -> str:
    # Computed on hover from the model; the item knows only its RNA path.
    found = _ROW_ITEM_PATH.search(row_item.path_from_id())
    if found is None:
        return ""
    view_index, row_index = int(found[1]), int(found[2])
    view = property_viewer_views.find_view(getattr(row_item.id_data, VIEWS_PROPERTY)[view_index].name)
    property_list = view.property_list_view.live_list() if view is not None else None
    if property_list is None or row_index >= len(property_list.rows):
        return ""
    row = property_list.rows[row_index]
    details = property_list.row_details(row)
    return property_descriptions.row_tooltip(details, row) if details is not None else ""


def _on_active_row_changed(properties: Any, _context: Any) -> None:
    # The list's own clicks and its Up and Down keys select the row.
    if widget_updates.is_writing_from_model():
        return
    view = property_viewer_views.find_view(properties.name)
    if view is None:
        return
    property_viewer_views.set_entering_search_text(view.name, is_entering=False)  # a click on a row ends typing
    before = view.property_list_view.selected_path
    view.property_list_view.select_row(properties.active_row_index)
    sync_and_notify(view, before)  # selecting reads any pending stage changes, which may change the rows


def _on_search_changed(properties: Any, _context: Any) -> None:
    # Typing updates the text on every keystroke, so the search runs a pause after the fields last changed.
    if widget_updates.is_writing_from_model():
        return
    view = property_viewer_views.find_view(properties.name)
    if view is not None:
        widget_updates.schedule(view.run_search, SEARCH_DELAY_SECONDS)


def _on_search_text_changed(properties: Any, context: Any) -> None:
    if not widget_updates.is_writing_from_model():
        property_viewer_views.set_entering_search_text(properties.name, is_entering=True)
    _on_search_changed(properties, context)


class PropertyViewerRow(bpy.types.PropertyGroup):
    """An item with no stored data: the UIList needs one per visible row, and reads the row from the model."""

    # For template_list's item_dyntip_propname.
    tooltip: bpy.props.StringProperty(get=_row_tooltip)  # ty: ignore[invalid-type-form]


def _column_units_property(title: str, default_units: float) -> Any:
    return bpy.props.FloatProperty(
        name="Width",
        description=f"The {title} column's width in UI units, where the list has room; the name takes the rest",
        default=default_units,
        min=1.0,
        soft_max=20.0,
        step=50,
        precision=1,
    )


class PropertyViewerViewProperties(bpy.types.PropertyGroup):
    """One view's rows, active row, search fields, and settings; its name is the view's."""

    rows: bpy.props.CollectionProperty(type=PropertyViewerRow)  # ty: ignore[invalid-type-form]
    active_row_index: bpy.props.IntProperty(default=-1, update=_on_active_row_changed)  # ty: ignore[invalid-type-form]
    show_value_column: bpy.props.BoolProperty(name="Show Value Column", default=True)  # ty: ignore[invalid-type-form]
    show_type_column: bpy.props.BoolProperty(name="Show Type Column", default=False)  # ty: ignore[invalid-type-form]
    show_copy_path_column: bpy.props.BoolProperty(name="Show Copy Path Column", default=True)  # ty: ignore[invalid-type-form]
    value_column_share: bpy.props.FloatProperty(  # ty: ignore[invalid-type-form]
        name="Share",
        description="The Value column's share of what the Type and Copy Path columns leave; the name takes the rest",
        default=0.6,
        min=0.5,
        max=0.9,
        subtype="FACTOR",
    )
    type_column_units: _column_units_property("Type", default_units=5.0)  # ty: ignore[invalid-type-form]
    search_text: bpy.props.StringProperty(name="Search", options={"TEXTEDIT_UPDATE"}, update=_on_search_text_changed)  # ty: ignore[invalid-type-form]
    search_mode: bpy.props.EnumProperty(  # ty: ignore[invalid-type-form]
        name="Match",
        items=search_box.match_mode_items(),
        update=_on_search_changed,
    )
    search_case_sensitive: bpy.props.BoolProperty(name="Match Case", update=_on_search_changed)  # ty: ignore[invalid-type-form]
    search_authored_only: bpy.props.BoolProperty(  # ty: ignore[invalid-type-form]
        name="Authored Only",
        default=True,
        description="Show only properties some layer has an opinion on, leaving out the schema's unauthored ones",
        update=_on_search_changed,
    )


# In registration order.
CLASSES = (PropertyViewerRow, PropertyViewerViewProperties)


def install_views_property() -> None:
    """Add the window manager's collection of view properties; the classes must be registered."""
    setattr(bpy.types.WindowManager, VIEWS_PROPERTY, bpy.props.CollectionProperty(type=PropertyViewerViewProperties))


def remove_views_property() -> None:
    """Remove the window manager's collection of view properties."""
    delattr(bpy.types.WindowManager, VIEWS_PROPERTY)


def view_properties(wm: Any, name: str) -> Any | None:
    """A view's properties, or None before they're made (as when a file has just loaded)."""
    return getattr(wm, VIEWS_PROPERTY).get(name)


def view_name_holding(hovered_property: Any) -> str | None:
    """The name of the view whose properties hold a property, as `context.property` gives one, or None.

    Over a list, the hovered property is its row's active index, so this names the list under the cursor.
    """
    return list_keys.item_name_holding(hovered_property, VIEWS_PROPERTY)


def create_missing_view_properties(wm: Any) -> None:
    """Make the properties of every view that has none, with its applied search, and sync every view's rows."""
    items = getattr(wm, VIEWS_PROPERTY)
    for view in property_viewer_views.all_views():
        if items.get(view.name) is None:
            properties = items.add()
            properties.name = view.name
            _write_query(properties, view.property_list_view.query)
        sync_rows(view.name)


def remove_view_properties(wm: Any, name: str) -> None:
    """Remove a view's properties, if it has any."""
    items = getattr(wm, VIEWS_PROPERTY)
    if (item_index := items.find(name)) >= 0:
        items.remove(item_index)


def sync_rows(name: str) -> None:
    """Resize a view's row items to its list's row count, and make the selected row the active one."""
    wm: Any = bpy.context.window_manager
    properties = view_properties(wm, name) if wm is not None else None
    if properties is None:
        return
    property_list_view = property_viewer_views.property_viewer_view(name).property_list_view
    property_list = property_list_view.live_list()
    row_count = len(property_list.rows) if property_list is not None else 0
    rows = properties.rows
    if len(rows) > row_count:
        rows.clear()  # removing items one by one from the end is quadratic
    for _ in range(row_count - len(rows)):
        rows.add()
    active_row_index = property_list_view.active_row_index()
    with widget_updates.writing_from_model():
        properties.active_row_index = -1 if active_row_index is None else active_row_index


def sync_and_notify(view: property_viewer_views.PropertyViewerView, before: Sdf.Path | None) -> None:
    """Sync a view's rows after its list or selection changed, and tell the host if the selection did."""
    sync_rows(view.name)
    property_viewer_views.notify_selection(view, before)


def query_from_properties(properties: Any) -> property_search.SearchQuery:
    """The search a view's properties hold."""
    return property_search.SearchQuery(
        text=properties.search_text,
        mode=text_matching.MatchMode[properties.search_mode],
        case_sensitive=properties.search_case_sensitive,
        authored_only=properties.search_authored_only,
    )


def _write_query(properties: Any, query: property_search.SearchQuery) -> None:
    with widget_updates.writing_from_model():
        properties.search_text = query.text
        properties.search_mode = query.mode.name
        properties.search_case_sensitive = query.case_sensitive
        properties.search_authored_only = query.authored_only


def apply_stage_changes(name: str) -> None:
    """Read a view's pending stage changes, then sync and redraw; the search fields wait for their own timer."""
    view = property_viewer_views.property_viewer_view(name)
    before = view.property_list_view.selected_path
    view.property_list_view.apply_pending_changes()
    sync_and_notify(view, before)
    widget_updates.redraw_all_areas()


def apply_pending(name: str) -> None:
    """Read a view's pending stage changes and apply its search if the fields changed, then sync and redraw."""
    view = property_viewer_views.property_viewer_view(name)
    property_list_view = view.property_list_view
    before = property_list_view.selected_path
    property_list_view.apply_pending_changes()
    wm: Any = bpy.context.window_manager
    properties = view_properties(wm, name) if wm is not None else None
    if properties is not None and (query := query_from_properties(properties)) != property_list_view.query:
        property_list_view.set_query(query)
    sync_and_notify(view, before)
    widget_updates.redraw_all_areas()
