"""The scene graph views by name: each a `PrimTreeView`, and what its host said about where and how it shows.

The registry knows nothing of the properties a view is drawn from; `widget_properties` keeps those. Hosts never see
a view, only its name (`widget_hosting`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from pxr import Sdf

    from ..prim_tree import PrimTreeView


class ViewNotFoundError(KeyError):
    """No scene graph view has the name given."""


@dataclass(frozen=True, slots=True)
class SceneGraphView:
    """One tree a host shows, and what its host said about where and how."""

    name: str
    prim_tree_view: PrimTreeView
    # (area, region) -> whether the region is drawing this view now; the key watcher asks it.
    shows_in_region: Callable[[Any, Any], bool]
    # Called with the selected prim's path, or None, when the selection changes other than through select_prim.
    on_selection_changed: Callable[[Sdf.Path | None], None]
    # The view's timers: one reads its stage's changes once an edit is over, the other runs its search a pause
    # after the fields last change. Apart, so typing doesn't put off reading a change.
    run_stage_changes: Callable[[], None]
    run_search: Callable[[], None]


class _SceneGraphViewsState:
    """The process's views, by name, in the order they were added, and those whose search text is being typed."""

    views: dict[str, SceneGraphView] = {}
    names_entering_search_text: set[str] = set()


def add_view(view: SceneGraphView) -> None:
    """Add a view under its name, which no other view may have."""
    if view.name in _SceneGraphViewsState.views:
        raise ValueError(f"a scene graph view named {view.name!r} exists")
    _SceneGraphViewsState.views[view.name] = view


def discard_view(name: str) -> SceneGraphView:
    """Take a view out of the registry, and return it."""
    view = scene_graph_view(name)
    del _SceneGraphViewsState.views[name]
    _SceneGraphViewsState.names_entering_search_text.discard(name)
    return view


def find_view(name: str) -> SceneGraphView | None:
    """The view with a name, or None."""
    return _SceneGraphViewsState.views.get(name)


def scene_graph_view(name: str) -> SceneGraphView:
    """The view with a name."""
    try:
        return _SceneGraphViewsState.views[name]
    except KeyError:
        raise ViewNotFoundError(name) from None


def set_entering_search_text(name: str, is_entering: bool) -> None:
    """Mark whether a view's search text is being typed, so the key watcher leaves Left and Right to its text box.

    Blender doesn't tell Python when a text field is being edited, so this starts when the text changes and ends at
    a key that ends an edit or a click on a row.
    """
    if is_entering:
        _SceneGraphViewsState.names_entering_search_text.add(name)
    else:
        _SceneGraphViewsState.names_entering_search_text.discard(name)


def is_entering_search_text(name: str) -> bool:
    """Whether a view's search text is being typed (set_entering_search_text)."""
    return name in _SceneGraphViewsState.names_entering_search_text


def stop_entering_search_text() -> None:
    """Mark no view's search text as being typed, after a key that ends a text edit."""
    _SceneGraphViewsState.names_entering_search_text.clear()


def all_views() -> list[SceneGraphView]:
    """Every view, in the order they were added."""
    return list(_SceneGraphViewsState.views.values())


def notify_selection(view: SceneGraphView, before: Sdf.Path | None) -> None:
    """Tell the host the view's selection, if it changed from before."""
    if view.prim_tree_view.selected_path != before:
        view.on_selection_changed(view.prim_tree_view.selected_path)
