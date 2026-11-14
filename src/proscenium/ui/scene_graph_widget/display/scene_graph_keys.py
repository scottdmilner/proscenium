"""The scene graph's views as lists the widgets' shared key watcher steps (`list_keys`): Left and Right over a tree.

Right expands a row, or steps into its first child; Left collapses it, or steps out to its parent; with Shift, either
applies to the row's whole subtree. A view whose search text is being typed leaves the keys to its text box.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...widget_resources import list_keys
from . import scene_graph_properties, scene_graph_views

if TYPE_CHECKING:
    from ...widget_model.list_steps import StepDirection


def _keyed_list(view: scene_graph_views.SceneGraphView) -> list_keys.KeyedList:
    def holds_property(hovered_property: Any) -> bool:
        return scene_graph_properties.view_name_holding(hovered_property) == view.name

    def is_steppable() -> bool:
        is_typing = scene_graph_views.is_entering_search_text(view.name)
        return view.prim_tree_view.live_tree() is not None and not is_typing

    def step(direction: StepDirection, recursive: bool) -> None:
        before = view.prim_tree_view.selected_path
        view.prim_tree_view.step(direction, recursive)
        scene_graph_properties.sync_and_notify(view, before)

    return list_keys.KeyedList(view.shows_in_region, holds_property, is_steppable, step)


KEYED_LISTS = list_keys.KeyedLists(
    lists=lambda: [_keyed_list(view) for view in scene_graph_views.all_views()],
    stop_entering_search_text=scene_graph_views.stop_entering_search_text,
)


def start_watching() -> None:
    """Add the scene graph's views to the key watchers, which start in every window if they aren't running."""
    list_keys.add_keyed_lists(KEYED_LISTS)


def stop_watching() -> None:
    """Take the scene graph's views from the key watchers, which end if no other widget's lists are left."""
    list_keys.remove_keyed_lists(KEYED_LISTS)
