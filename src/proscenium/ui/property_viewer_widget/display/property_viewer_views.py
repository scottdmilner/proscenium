"""The property viewer's views by name: each a `PropertyListView`, and what its host said about where it shows.

The registry knows nothing of the properties a view is drawn from; `property_viewer_properties` keeps those. Hosts
never see a view, only its name (`property_viewer_hosting`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from pxr import Sdf

    from ..property_list import PropertyListView


class ViewNotFoundError(KeyError):
    """No property viewer view has the name given."""


@dataclass(frozen=True, slots=True)
class PropertyViewerView:
    """One property list a host shows, where it shows, who hears its selection, and who takes its jumps."""

    name: str
    property_list_view: PropertyListView
    # (area, region) -> whether the region is drawing this view now; the key watcher asks it.
    shows_in_region: Callable[[Any, Any], bool]
    # Called with the selected property's path, or None, when the selection changes other than through
    # select_property.
    on_selection_changed: Callable[[Sdf.Path | None], None]
    # Called with a target's path when its row's jump button is clicked, to select it where the host shows it, such
    # as in a scene graph; None draws no jump buttons.
    on_jump_to_target: Callable[[Sdf.Path], None] | None
    # The view's timers: one reads its stage's changes once an edit is over, the other runs its search a pause
    # after the fields last change.
    run_stage_changes: Callable[[], None]
    run_search: Callable[[], None]


class _PropertyViewerViewsState:
    """The process's views, by name, in the order they were added, and those whose search text is being typed."""

    views: dict[str, PropertyViewerView] = {}
    names_entering_search_text: set[str] = set()


def add_view(view: PropertyViewerView) -> None:
    """Add a view under its name, which no other view may have."""
    if view.name in _PropertyViewerViewsState.views:
        raise ValueError(f"a property viewer view named {view.name!r} exists")
    _PropertyViewerViewsState.views[view.name] = view


def discard_view(name: str) -> PropertyViewerView:
    """Take a view out of the registry, and return it."""
    view = property_viewer_view(name)
    del _PropertyViewerViewsState.views[name]
    _PropertyViewerViewsState.names_entering_search_text.discard(name)
    return view


def find_view(name: str) -> PropertyViewerView | None:
    """The view with a name, or None."""
    return _PropertyViewerViewsState.views.get(name)


def property_viewer_view(name: str) -> PropertyViewerView:
    """The view with a name."""
    try:
        return _PropertyViewerViewsState.views[name]
    except KeyError:
        raise ViewNotFoundError(name) from None


def set_entering_search_text(name: str, is_entering: bool) -> None:
    """Mark whether a view's search text is being typed, so the key watcher leaves Left and Right to its text box.

    Blender doesn't tell Python when a text field is being edited, so this starts when the text changes and ends at
    a key that ends an edit or a click on a row.
    """
    if is_entering:
        _PropertyViewerViewsState.names_entering_search_text.add(name)
    else:
        _PropertyViewerViewsState.names_entering_search_text.discard(name)


def is_entering_search_text(name: str) -> bool:
    """Whether a view's search text is being typed (set_entering_search_text)."""
    return name in _PropertyViewerViewsState.names_entering_search_text


def stop_entering_search_text() -> None:
    """Mark no view's search text as being typed, after a key that ends a text edit."""
    _PropertyViewerViewsState.names_entering_search_text.clear()


def all_views() -> list[PropertyViewerView]:
    """Every view, in the order they were added."""
    return list(_PropertyViewerViewsState.views.values())


def notify_selection(view: PropertyViewerView, before: Sdf.Path | None) -> None:
    """Tell the host the view's selection, if it changed from before."""
    if view.property_list_view.selected_path != before:
        view.on_selection_changed(view.property_list_view.selected_path)
