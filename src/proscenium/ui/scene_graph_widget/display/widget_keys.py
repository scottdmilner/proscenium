"""Left and Right arrow keys for scene graph views, taken by a modal operator before the UIList sees them.

Over a list, the UIList's own handler takes all four arrow keys to move its active row, ahead of every keymap, and
its update callback can't tell which key moved it. A modal operator's handler runs before the regions' handlers, so
it sees each event first: it takes Left and Right (and Shift with them) while the cursor is over a region a view's
host says is showing that view, and passes every other event on. Up and Down stay with the list.

A modal operator is per window, so each window gets its own watcher, tracked by the window it runs in: one starts in
every window at registration, and drawing a view starts one in any window that has none, such as a window opened
since, or every window after a file load ends them all. Every event reaches every modal operator, so the watcher
returns at once from any it doesn't take.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy

from ..prim_tree import StepDirection
from . import widget_properties, widget_views

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

KEY_DIRECTIONS = {"RIGHT_ARROW": StepDirection.INTO, "LEFT_ARROW": StepDirection.OUT_OF}
START_DELAY_SECONDS = 0.1  # after registration, once the windows exist


class _SceneGraphKeysState:
    """Whether the watchers should keep running, and which windows have one."""

    is_watching = False  # cleared to end every watcher at its next event
    watched_window_pointers: set[int] = set()  # Window.as_pointer() of each window with a running watcher


def _contains(rect: Any, event: Any) -> bool:
    return rect.x <= event.mouse_x < rect.x + rect.width and rect.y <= event.mouse_y < rect.y + rect.height


def _view_under_cursor(window: Any, event: Any) -> tuple[widget_views.SceneGraphView, Any] | None:
    """The view whose host draws it in the region under the cursor, and that region."""
    area = next((area for area in window.screen.areas if _contains(area, event)), None)
    if area is None:
        return None
    # A 3D View's sidebar overlaps its main region, so any region under the cursor that shows a view counts.
    for region in area.regions:
        if not _contains(region, event):
            continue
        for view in widget_views.all_views():
            if view.shows_in_region(area, region):
                return view, region
    return None


class SceneGraphWatchKeys(bpy.types.Operator):
    """Take Left and Right over a scene graph view before its UIList does."""

    bl_idname = "proscenium.scene_graph_watch_keys"
    bl_label = "Watch Scene Graph Keys"
    bl_options = {"INTERNAL"}

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        window_pointer = context.window.as_pointer()
        if window_pointer in _SceneGraphKeysState.watched_window_pointers:
            return {"CANCELLED"}  # the window has one
        _SceneGraphKeysState.watched_window_pointers.add(window_pointer)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    @override
    def modal(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        if not _SceneGraphKeysState.is_watching:
            _SceneGraphKeysState.watched_window_pointers.discard(context.window.as_pointer())
            return {"CANCELLED", "PASS_THROUGH"}  # without PASS_THROUGH, ending would consume the event
        direction = KEY_DIRECTIONS.get(event.type)
        if direction is None or event.value != "PRESS" or event.ctrl or event.alt or event.oskey:
            return {"PASS_THROUGH"}
        found = _view_under_cursor(context.window, event)
        if found is None or found[0].prim_tree_view.live_tree() is None:
            return {"PASS_THROUGH"}
        view, region = found
        before = view.prim_tree_view.selected_path
        view.prim_tree_view.step(direction, recursive=event.shift)
        widget_properties.sync_and_notify(view, before)
        region.tag_redraw()
        return {"RUNNING_MODAL"}  # consumed: neither the list nor the Frames keymap sees it

    @override
    def cancel(self, context: Any) -> None:
        # Blender cancels a running modal operator when its window closes.
        if context.window is not None:
            _SceneGraphKeysState.watched_window_pointers.discard(context.window.as_pointer())


def _start_missing_watchers() -> None:
    # A timer, so it returns None: a draw can't invoke an operator, so it schedules this.
    wm: Any = bpy.context.window_manager
    if not _SceneGraphKeysState.is_watching or wm is None:
        return
    for window in wm.windows:
        if window.as_pointer() in _SceneGraphKeysState.watched_window_pointers:
            continue
        override: Any = bpy.context.temp_override(window=window)  # the stubs miss its context manager methods
        with override:
            bpy.ops.proscenium.scene_graph_watch_keys("INVOKE_DEFAULT")  # ty: ignore[unresolved-attribute]


def _schedule_start(delay_seconds: float) -> None:
    # Nothing in background mode, which has no windows.
    if not bpy.app.background and not bpy.app.timers.is_registered(_start_missing_watchers):
        bpy.app.timers.register(_start_missing_watchers, first_interval=delay_seconds)


def start_watching() -> None:
    """Start a watcher in every window, once the windows exist."""
    _SceneGraphKeysState.is_watching = True
    _schedule_start(START_DELAY_SECONDS)


def ensure_watcher(window: Any) -> None:
    """Start a watcher in a window that draws a view, if the watchers are running and it has none."""
    if (
        _SceneGraphKeysState.is_watching
        and window is not None
        and window.as_pointer() not in _SceneGraphKeysState.watched_window_pointers
    ):
        _schedule_start(0.0)


def forget_watchers() -> None:
    """Untrack every window's watcher, once a file load has ended them all."""
    _SceneGraphKeysState.watched_window_pointers.clear()


def stop_watching() -> None:
    """End every watcher at its next event."""
    _SceneGraphKeysState.is_watching = False
    if bpy.app.timers.is_registered(_start_missing_watchers):
        bpy.app.timers.unregister(_start_missing_watchers)


# In registration order.
CLASSES = (SceneGraphWatchKeys,)
