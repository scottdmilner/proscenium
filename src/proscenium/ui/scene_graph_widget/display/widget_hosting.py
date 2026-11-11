"""What a host calls to create views, give them stages, select in them, and read their selections.

A host names a view in each call and never holds it, so every change goes through these and keeps the view's
properties and its host's callback in step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy

from ..prim_tree import PrimTreeView
from . import widget_properties, widget_views

if TYPE_CHECKING:
    from collections.abc import Callable

    from pxr import Sdf, Usd


def create_view(
    name: str,
    shows_in_region: Callable[[Any, Any], bool],
    on_selection_changed: Callable[[Sdf.Path | None], None] | None = None,
) -> None:
    """Create a view, showing no stage until set_stage gives it one, and make its properties.

    shows_in_region(area, region) says whether a region is drawing the view now, for the key watcher.
    on_selection_changed hears each change of selection but select_prim's: one made in the tree, a new stage
    selecting nothing, and the selected prim leaving the stage (None).
    """

    def run_pending() -> None:
        widget_properties.apply_pending(name)

    def schedule_stage_change() -> None:
        widget_properties.schedule(run_pending, 0.0)  # the notice comes mid-edit; read it once the edit is over

    view = widget_views.SceneGraphView(
        name=name,
        prim_tree_view=PrimTreeView(schedule_stage_change),
        shows_in_region=shows_in_region,
        on_selection_changed=on_selection_changed or (lambda _path: None),
        run_pending=run_pending,
    )
    widget_views.add_view(view)
    wm = bpy.context.window_manager
    if wm is not None:
        widget_properties.create_missing_view_properties(wm)


def remove_view(name: str) -> None:
    """Stop showing a view's stage, and remove the view and its properties."""
    view = widget_views.discard_view(name)
    widget_properties.unschedule(view.run_pending)
    view.prim_tree_view.close()
    wm = bpy.context.window_manager
    if wm is not None:
        widget_properties.remove_view_properties(wm, name)


def remove_all_views() -> None:
    """Remove every view."""
    for view in widget_views.all_views():
        remove_view(view.name)


def set_stage(name: str, stage: Usd.Stage | None) -> None:
    """Show a stage in a view, or none. The view holds the stage's prims, never the stage."""
    view = widget_views.scene_graph_view(name)
    before = view.prim_tree_view.selected_path
    view.prim_tree_view.set_stage(stage)
    widget_properties.sync_and_notify(view, before)


def selected_path(name: str) -> Sdf.Path | None:
    """The path of the prim selected in a view, or None."""
    return widget_views.scene_graph_view(name).prim_tree_view.selected_path


def select_prim(name: str, path: Sdf.Path | None) -> None:
    """Select a prim in a view, revealing its row, as a selection made elsewhere would; the host isn't told.

    A path the view's stage has no prim at selects nothing.
    """
    view = widget_views.scene_graph_view(name)
    if path is None:
        view.prim_tree_view.select_row(None)
    else:
        view.prim_tree_view.select_path(path)
    widget_properties.sync_rows(name)
