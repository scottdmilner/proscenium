"""What a host calls to create views, show a prim in them, select in them, and read their selections.

A host names a view in each call and never holds it, so every change goes through these and keeps the view's
properties and its host's callback in step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy

from ... import widget_updates
from ..property_list import PropertyListView
from . import prim_summary, property_viewer_properties, property_viewer_views

if TYPE_CHECKING:
    from collections.abc import Callable

    from pxr import Sdf, Usd


def create_view(
    name: str,
    shows_in_region: Callable[[Any, Any], bool],
    on_selection_changed: Callable[[Sdf.Path | None], None] | None = None,
    on_jump_to_target: Callable[[Sdf.Path], None] | None = None,
) -> None:
    """Create a view, showing no stage until set_stage gives it one, and make its properties.

    shows_in_region(area, region) says whether a region is drawing the view now, for the key watcher.
    on_selection_changed hears each change of the selected property's path but select_property's: one made in the
    list, another prim shown, and the selected property leaving the stage (None). on_jump_to_target, if given, is
    called with a target's path when the jump button on its row is clicked, for the host to select it where it shows
    it, as in a scene graph; without it, target rows draw no jump button.
    """

    def run_stage_changes() -> None:
        property_viewer_properties.apply_stage_changes(name)

    def run_search() -> None:
        property_viewer_properties.apply_pending(name)

    def schedule_stage_change() -> None:
        widget_updates.schedule(run_stage_changes, 0.0)  # the notice comes mid-edit; read it once the edit is over

    view = property_viewer_views.PropertyViewerView(
        name=name,
        property_list_view=PropertyListView(schedule_stage_change),
        shows_in_region=shows_in_region,
        on_selection_changed=on_selection_changed or (lambda _path: None),
        on_jump_to_target=on_jump_to_target,
        run_stage_changes=run_stage_changes,
        run_search=run_search,
    )
    property_viewer_views.add_view(view)
    wm = bpy.context.window_manager
    if wm is not None:
        property_viewer_properties.create_missing_view_properties(wm)


def remove_view(name: str) -> None:
    """Stop showing a view's stage, and remove the view and its properties."""
    view = property_viewer_views.discard_view(name)
    widget_updates.unschedule(view.run_stage_changes)
    widget_updates.unschedule(view.run_search)
    view.property_list_view.close()
    prim_summary.forget_summary(name)
    wm = bpy.context.window_manager
    if wm is not None:
        property_viewer_properties.remove_view_properties(wm, name)


def remove_all_views() -> None:
    """Remove every view."""
    for view in property_viewer_views.all_views():
        remove_view(view.name)


def _change(name: str, change: Callable[[PropertyListView], None]) -> None:
    """Change a view, then sync its rows, and tell the host if its selection changed."""
    view = property_viewer_views.property_viewer_view(name)
    before = view.property_list_view.selected_path
    change(view.property_list_view)
    property_viewer_properties.sync_and_notify(view, before)


def set_stage(name: str, stage: Usd.Stage | None) -> None:
    """Show a stage in a view, or none, with no prim until show_prim; the view never holds the stage."""
    _change(name, lambda property_list_view: property_list_view.set_stage(stage))


def show_prim(name: str, path: Sdf.Path | None) -> None:
    """Show the properties of the prim at a path on the view's stage, or none.

    The selected property stays selected where the prim has one of its name, and the expanded ones stay expanded.
    """
    _change(name, lambda property_list_view: property_list_view.show_prim(path))


def set_time_code(name: str, time_code: Usd.TimeCode) -> None:
    """Show the values at a time code, such as the scene's current frame's; a view starts at the default time code."""
    view = property_viewer_views.property_viewer_view(name)
    if view.property_list_view.time_code != time_code:
        view.property_list_view.set_time_code(time_code)
        widget_updates.redraw_all_areas()


def selected_path(name: str) -> Sdf.Path | None:
    """The path of the property selected in a view, or None, as when its stage has been released."""
    return property_viewer_views.property_viewer_view(name).property_list_view.selected_path


def select_property(name: str, property_name: str | None) -> None:
    """Select a property of the shown prim by name, or nothing, as a selection made elsewhere; the host isn't told."""
    property_viewer_views.property_viewer_view(name).property_list_view.select_property(property_name)
    property_viewer_properties.sync_rows(name)
