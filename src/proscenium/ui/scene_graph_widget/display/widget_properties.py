"""The properties a scene graph view is drawn from, and keeping them in step with the view's tree.

Each view's properties are an item of the window manager's `proscenium_scene_graph_views` collection, named for the
view: one empty row item per visible row, the active row, and the search fields. The window manager's properties
aren't saved, and loading a file replaces them, so the items are made again after each load. Everything that reads
or writes these properties is here, with their update callbacks.

The view is what owns its state; the properties mirror it. The search fields are the one exception, the query being
edited: a pause after they last change, `apply_pending` applies them to the view, whose `query` is then the applied
one. Properties made for an existing view, as after a load, start from its applied query.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import bpy

from ..prim_tree import prim_descriptions, prim_search
from . import widget_views

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from pxr import Sdf

VIEWS_PROPERTY = "proscenium_scene_graph_views"  # the WindowManager's collection of SceneGraphViewProperties
SEARCH_DELAY_SECONDS = 0.25  # after the last keystroke, before a search runs
# A row item's RNA path: "proscenium_scene_graph_views[<view index>].rows[<row index>]".
_ROW_ITEM_PATH = re.compile(rf"{VIEWS_PROPERTY}\[(\d+)\]\.rows\[(\d+)\]$")


class _SceneGraphPropertiesState:
    is_writing_from_view = False  # set while the properties are written from the view, so no update callback runs


def _row_tooltip(row_item: Any) -> str:
    # Computed on hover from the model; the item knows only its RNA path.
    found = _ROW_ITEM_PATH.search(row_item.path_from_id())
    if found is None:
        return ""
    view_index, row_index = int(found[1]), int(found[2])
    view = widget_views.find_view(getattr(row_item.id_data, VIEWS_PROPERTY)[view_index].name)
    tree = view.prim_tree_view.live_tree() if view is not None else None
    if tree is None or row_index >= len(tree.rows):
        return ""
    return prim_descriptions.row_tooltip(tree.rows[row_index].prim)


def _on_active_row_changed(properties: Any, _context: Any) -> None:
    # The list's own clicks and its Up and Down keys select the row's prim.
    if _SceneGraphPropertiesState.is_writing_from_view:
        return
    view = widget_views.find_view(properties.name)
    if view is None:
        return
    before = view.prim_tree_view.selected_path
    view.prim_tree_view.select_row(properties.active_row_index)
    widget_views.notify_selection(view, before)


def _on_search_changed(properties: Any, _context: Any) -> None:
    # Typing updates the text on every keystroke, so the search runs a pause after the fields last changed.
    if _SceneGraphPropertiesState.is_writing_from_view:
        return
    view = widget_views.find_view(properties.name)
    if view is not None:
        schedule(view.run_pending, SEARCH_DELAY_SECONDS)


class SceneGraphRow(bpy.types.PropertyGroup):
    """An item with no stored data: the UIList needs one per visible row, and reads the row from the model."""

    # For template_list's item_dyntip_propname.
    tooltip: bpy.props.StringProperty(get=_row_tooltip)  # ty: ignore[invalid-type-form]


class SceneGraphViewProperties(bpy.types.PropertyGroup):
    """One view's rows, active row, and search fields; its name is the view's."""

    rows: bpy.props.CollectionProperty(type=SceneGraphRow)  # ty: ignore[invalid-type-form]
    active_row_index: bpy.props.IntProperty(default=-1, update=_on_active_row_changed)  # ty: ignore[invalid-type-form]
    show_kind_column: bpy.props.BoolProperty(name="Show Kind Column", default=True)  # ty: ignore[invalid-type-form]
    show_type_column: bpy.props.BoolProperty(name="Show Type Column", default=True)  # ty: ignore[invalid-type-form]
    shown_name: bpy.props.EnumProperty(  # ty: ignore[invalid-type-form]
        name="Names",
        description="Which name each row shows",
        items=[
            ("NAME", "Prim", "Each prim's name"),
            ("DISPLAY_NAME", "Display Name", "Each prim's displayName, or its name where it has none"),
        ],
    )
    search_text: bpy.props.StringProperty(name="Search", options={"TEXTEDIT_UPDATE"}, update=_on_search_changed)  # ty: ignore[invalid-type-form]
    search_mode: bpy.props.EnumProperty(  # ty: ignore[invalid-type-form]
        name="Match",
        items=[(mode.name, mode.value.capitalize(), "") for mode in prim_search.SearchMode],
        update=_on_search_changed,
    )
    search_case_sensitive: bpy.props.BoolProperty(name="Match Case", update=_on_search_changed)  # ty: ignore[invalid-type-form]
    search_type_name: bpy.props.StringProperty(  # ty: ignore[invalid-type-form]
        name="Type", description="A schema type the prim must be, such as Mesh or Gprim", update=_on_search_changed
    )
    # One toggle per flag: an expanded ENUM_FLAG sets one item per click, and no click clears them all.
    search_payload: bpy.props.BoolProperty(name="Payload", update=_on_search_changed)  # ty: ignore[invalid-type-form]
    search_variants: bpy.props.BoolProperty(name="Variants", update=_on_search_changed)  # ty: ignore[invalid-type-form]
    search_instance: bpy.props.BoolProperty(name="Instance", update=_on_search_changed)  # ty: ignore[invalid-type-form]
    search_inactive: bpy.props.BoolProperty(name="Inactive", update=_on_search_changed)  # ty: ignore[invalid-type-form]


# The property each search flag is toggled by, above.
FLAG_PROPERTY_NAMES = {
    prim_search.SearchFlag.PAYLOAD: "search_payload",
    prim_search.SearchFlag.VARIANTS: "search_variants",
    prim_search.SearchFlag.INSTANCE: "search_instance",
    prim_search.SearchFlag.INACTIVE: "search_inactive",
}

# In registration order.
CLASSES = (SceneGraphRow, SceneGraphViewProperties)


def install_views_property() -> None:
    """Add the window manager's collection of view properties; the classes must be registered."""
    setattr(bpy.types.WindowManager, VIEWS_PROPERTY, bpy.props.CollectionProperty(type=SceneGraphViewProperties))


def remove_views_property() -> None:
    """Remove the window manager's collection of view properties."""
    delattr(bpy.types.WindowManager, VIEWS_PROPERTY)


def view_properties(wm: Any, name: str) -> Any | None:
    """A view's properties, or None before they're made (as when a file has just loaded)."""
    return getattr(wm, VIEWS_PROPERTY).get(name)


def create_missing_view_properties(wm: Any) -> None:
    """Make the properties of every view that has none, with its applied search, and sync every view's rows."""
    items = getattr(wm, VIEWS_PROPERTY)
    for view in widget_views.all_views():
        if items.get(view.name) is None:
            properties = items.add()
            properties.name = view.name
            _write_query(properties, view.prim_tree_view.query)
        sync_rows(view.name)


def remove_view_properties(wm: Any, name: str) -> None:
    """Remove a view's properties, if it has any."""
    items = getattr(wm, VIEWS_PROPERTY)
    if (item_index := items.find(name)) >= 0:
        items.remove(item_index)


def sync_rows(name: str) -> None:
    """Resize a view's row items to its tree's row count, and make the selected prim's row the active one."""
    wm: Any = bpy.context.window_manager
    properties = view_properties(wm, name) if wm is not None else None
    if properties is None:
        return
    prim_tree_view = widget_views.scene_graph_view(name).prim_tree_view
    tree = prim_tree_view.live_tree()
    row_count = len(tree.rows) if tree is not None else 0
    rows = properties.rows
    if len(rows) > row_count:
        rows.clear()  # removing items one by one from the end is quadratic
    for _ in range(row_count - len(rows)):
        rows.add()
    active_row_index = prim_tree_view.active_row_index()
    with _writing_from_view():
        properties.active_row_index = -1 if active_row_index is None else active_row_index


def sync_and_notify(view: widget_views.SceneGraphView, before: Sdf.Path | None) -> None:
    """Sync a view's rows after its tree or selection changed, and tell the host if the selection did."""
    sync_rows(view.name)
    widget_views.notify_selection(view, before)


def query_from_properties(properties: Any) -> prim_search.SearchQuery:
    """The search a view's properties hold."""
    return prim_search.SearchQuery(
        text=properties.search_text,
        mode=prim_search.SearchMode[properties.search_mode],
        case_sensitive=properties.search_case_sensitive,
        type_name=properties.search_type_name.strip(),
        flags=frozenset(flag for flag, name in FLAG_PROPERTY_NAMES.items() if getattr(properties, name)),
    )


def _write_query(properties: Any, query: prim_search.SearchQuery) -> None:
    with _writing_from_view():
        properties.search_text = query.text
        properties.search_mode = query.mode.name
        properties.search_case_sensitive = query.case_sensitive
        properties.search_type_name = query.type_name
        for flag, property_name in FLAG_PROPERTY_NAMES.items():
            setattr(properties, property_name, flag in query.flags)


@contextmanager
def _writing_from_view() -> Iterator[None]:
    # Blender 5 keeps bpy.props apart from dict-style ID properties, so only a flag stops the update callbacks.
    _SceneGraphPropertiesState.is_writing_from_view = True
    try:
        yield
    finally:
        _SceneGraphPropertiesState.is_writing_from_view = False


def apply_pending(name: str) -> None:
    """Read a view's pending stage changes and run its search if the fields changed, then sync and redraw."""
    view = widget_views.scene_graph_view(name)
    prim_tree_view = view.prim_tree_view
    before = prim_tree_view.selected_path
    prim_tree_view.apply_pending_changes()
    wm: Any = bpy.context.window_manager
    properties = view_properties(wm, name) if wm is not None else None
    if properties is not None and (query := query_from_properties(properties)) != prim_tree_view.query:
        prim_tree_view.set_query(query)
    sync_and_notify(view, before)
    _tag_redraw_all()


def schedule(timer: Callable[[], None], delay_seconds: float) -> None:
    """Run a view's timer after a delay, restarting the delay if it's already waiting; a file load doesn't cancel it."""
    unschedule(timer)
    # A view marks a stage change pending once, until the timer reads it, so a lost timer would stop its updates.
    bpy.app.timers.register(timer, first_interval=delay_seconds, persistent=True)


def unschedule(timer: Callable[[], None]) -> None:
    """Cancel a view's timer if it's waiting."""
    if bpy.app.timers.is_registered(timer):
        bpy.app.timers.unregister(timer)


def _tag_redraw_all() -> None:
    # Hosts draw views wherever they like, so every area redraws.
    wm: Any = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            area.tag_redraw()
