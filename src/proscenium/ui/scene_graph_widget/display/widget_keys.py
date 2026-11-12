"""Left and Right arrow keys for scene graph views, taken by a modal operator before the UIList sees them.

Over a list, the UIList's own handler takes all four arrow keys to move its active row, ahead of every keymap, and
its update callback can't tell which key moved it. A modal operator's handler runs before the regions' handlers, so
it sees each event first: it takes Left and Right (and Shift with them) while the cursor is over a region a view's
host says is showing that view, and in a region showing several, over a row of that view's list; it passes every
other event on. Up and Down stay with the list.

It runs before a text field being edited, too, and Blender doesn't tell Python when one is. So once a view's search
text changes, it leaves Left and Right to the text box until a key that ends a text edit (ENDING_EDIT_KEYS) or a
click on one of the view's rows.

A modal operator is per window, so each window gets its own watcher: one starts in every window at registration, and
drawing a view starts one in any window whose running modal operators don't include one, such as a window opened
since, every window after a file load ends them all, or every window after the widget is registered again, since
unregistering its operator ends each watcher. Every event reaches every modal operator, so the watcher returns at
once from any it doesn't take.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy

from ..prim_tree import StepDirection
from . import widget_properties, widget_views

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

KEY_DIRECTIONS = {"RIGHT_ARROW": StepDirection.INTO, "LEFT_ARROW": StepDirection.OUT_OF}
ENDING_EDIT_KEYS = frozenset({"RET", "NUMPAD_ENTER", "ESC", "TAB"})
START_DELAY_SECONDS = 0.1  # after registration, once the windows exist
WATCHER_RUNNING_IDNAME = "PROSCENIUM_OT_scene_graph_watch_keys"  # how a window's modal operators name a watcher


class _SceneGraphKeysState:
    """Whether the watchers should keep running."""

    is_watching = False  # cleared to end every watcher at its next event


def _contains(rect: Any, event: Any) -> bool:
    return rect.x <= event.mouse_x < rect.x + rect.width and rect.y <= event.mouse_y < rect.y + rect.height


def _hovered_view_name(window: Any, area: Any, region: Any) -> str | None:
    # The watcher's own context has no region, so it reads the region's hovered button through an override.
    override: Any = bpy.context.temp_override(window=window, area=area, region=region)
    with override:
        return widget_properties.view_name_holding(getattr(bpy.context, "property", None))


def _view_under_cursor(window: Any, event: Any) -> tuple[widget_views.SceneGraphView, Any] | None:
    """The view whose host draws it under the cursor, and the region it's in.

    In a region showing several views, it's the one whose list is under the cursor, or None between them.
    """
    area = next((area for area in window.screen.areas if _contains(area, event)), None)
    if area is None:
        return None
    # A 3D View's sidebar overlaps its main region, so any region under the cursor that shows a view counts.
    for region in area.regions:
        if not _contains(region, event):
            continue
        shown = [view for view in widget_views.all_views() if view.shows_in_region(area, region)]
        if len(shown) == 1:
            return shown[0], region
        if shown:
            # Over a row, the hovered property is its list's active row; over a button in it, none is, so the key
            # passes on rather than step a view that may not be the one under the cursor.
            hovered_name = _hovered_view_name(window, area, region)
            view = next((view for view in shown if view.name == hovered_name), None)
            return (view, region) if view is not None else None
    return None


def _has_watcher(window: Any) -> bool:
    # A window lists its running modal operators by their C-style idnames; an ended one's entry reads None.
    return any(
        operator is not None and operator.bl_idname == WATCHER_RUNNING_IDNAME for operator in window.modal_operators
    )


class SceneGraphWatchKeys(bpy.types.Operator):
    """Take Left and Right over a scene graph view before its UIList does."""

    bl_idname = "proscenium.scene_graph_watch_keys"
    bl_label = "Watch Scene Graph Keys"
    bl_options = {"INTERNAL"}

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        if _has_watcher(context.window):
            return {"CANCELLED"}
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    @override
    def modal(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        if not _SceneGraphKeysState.is_watching:
            return {"CANCELLED", "PASS_THROUGH"}  # without PASS_THROUGH, ending would consume the event
        if event.type in ENDING_EDIT_KEYS and event.value == "PRESS":
            widget_views.stop_entering_search_text()
            return {"PASS_THROUGH"}
        direction = KEY_DIRECTIONS.get(event.type)
        if direction is None or event.value != "PRESS" or event.ctrl or event.alt or event.oskey:
            return {"PASS_THROUGH"}
        found = _view_under_cursor(context.window, event)
        if found is None or found[0].prim_tree_view.live_tree() is None:
            return {"PASS_THROUGH"}
        view, region = found
        if widget_views.is_entering_search_text(view.name):
            return {"PASS_THROUGH"}  # for the search's text box
        before = view.prim_tree_view.selected_path
        view.prim_tree_view.step(direction, recursive=event.shift)
        widget_properties.sync_and_notify(view, before)
        region.tag_redraw()
        return {"RUNNING_MODAL"}  # consumed: neither the list nor the Frames keymap sees it


def _start_missing_watchers() -> None:
    # A timer, so it returns None: a draw can't invoke an operator, so it schedules this.
    wm: Any = bpy.context.window_manager
    if not _SceneGraphKeysState.is_watching or wm is None:
        return
    for window in wm.windows:
        if _has_watcher(window):
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
    if _SceneGraphKeysState.is_watching and window is not None and not _has_watcher(window):
        _schedule_start(0.0)


def stop_watching() -> None:
    """End every watcher at its next event."""
    _SceneGraphKeysState.is_watching = False
    if bpy.app.timers.is_registered(_start_missing_watchers):
        bpy.app.timers.unregister(_start_missing_watchers)


# In registration order.
CLASSES = (SceneGraphWatchKeys,)
