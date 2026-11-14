"""The property viewer's views as lists the widgets' shared key watcher steps (`list_keys`): Left and Right.

Right shows a property's targets, or steps into its first; Left hides them, or steps out of a target to its property;
with Shift, every property's targets show or hide. A view whose search text is being typed leaves the keys to its
text box.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...widget_resources import list_keys
from . import property_viewer_properties, property_viewer_views

if TYPE_CHECKING:
    from ...widget_model.list_steps import StepDirection


def _keyed_list(view: property_viewer_views.PropertyViewerView) -> list_keys.KeyedList:
    def holds_property(hovered_property: Any) -> bool:
        return property_viewer_properties.view_name_holding(hovered_property) == view.name

    def is_steppable() -> bool:
        is_typing = property_viewer_views.is_entering_search_text(view.name)
        return view.property_list_view.live_list() is not None and not is_typing

    def step(direction: StepDirection, every_property: bool) -> None:
        before = view.property_list_view.selected_path
        view.property_list_view.step(direction, every_property)
        property_viewer_properties.sync_and_notify(view, before)

    return list_keys.KeyedList(view.shows_in_region, holds_property, is_steppable, step)


KEYED_LISTS = list_keys.KeyedLists(
    lists=lambda: [_keyed_list(view) for view in property_viewer_views.all_views()],
    stop_entering_search_text=property_viewer_views.stop_entering_search_text,
)


def start_watching() -> None:
    """Add the property viewer's views to the key watchers, which start in every window if they aren't running."""
    list_keys.add_keyed_lists(KEYED_LISTS)


def stop_watching() -> None:
    """Take the property viewer's views from the key watchers, which end if no other widget's lists are left."""
    list_keys.remove_keyed_lists(KEYED_LISTS)
