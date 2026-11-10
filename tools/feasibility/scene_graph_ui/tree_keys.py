"""Left and Right arrow keys for the tree, taken by a modal operator before the UIList sees them.

Over a list, the UIList's own handler takes all four arrow keys to move its active row, ahead of every keymap, and
its update callback can't tell which key moved it. A modal operator's handler runs before the regions' handlers, so
it sees each event first: it takes Left and Right (and Shift with them) while the cursor is over a region showing
the tree, and passes every other event on. Up and Down stay with the list.

A modal operator is per window and ends when a file loads, so one starts in each window at registration and again
after each load.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy
from bpy.app.handlers import persistent

if TYPE_CHECKING:
    from collections.abc import Callable

    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

KEYS = {"RIGHT_ARROW": "IN", "LEFT_ARROW": "OUT"}
KEY_HINTS = "Right: expand, or step in    Left: collapse, or step out    Shift: the whole subtree"


class _TreeKeyboardWatcherState:
    """The tree-navigation callbacks and whether key watchers are active."""

    # step(window manager, direction, recursive) moves through the tree; set by `register`.
    step: Callable[[Any, str, bool], None] = lambda _wm, _direction, _recursive: None
    # is_tree_region(area, region): whether the region is showing the tree; set by `register`.
    is_tree_region: Callable[[Any, Any], bool] = lambda _area, _region: False
    watching = False  # cleared to end every watcher at its next event


def _contains(rect: Any, event: Any) -> bool:
    return rect.x <= event.mouse_x < rect.x + rect.width and rect.y <= event.mouse_y < rect.y + rect.height


def _tree_region(window: Any, event: Any) -> Any:
    """The region under the cursor, if it is showing the tree."""
    area = next((area for area in window.screen.areas if _contains(area, event)), None)
    if area is None:
        return None
    # A 3D View's sidebar overlaps its main region, so any region under the cursor that shows the tree counts.
    return next(
        (r for r in area.regions if _contains(r, event) and _TreeKeyboardWatcherState.is_tree_region(area, r)), None
    )


class POC_SG_OT_watch_keys(bpy.types.Operator):  # noqa: N801 - Blender's class naming
    """Take Left and Right over the tree's sidebar before the UIList does."""

    bl_idname = "poc_sg.watch_keys"
    bl_label = "Watch Tree Keys"
    bl_options = {"INTERNAL"}

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    @override
    def modal(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        if not _TreeKeyboardWatcherState.watching:
            return {"CANCELLED", "PASS_THROUGH"}  # without PASS_THROUGH, ending would consume the event
        direction = KEYS.get(event.type)
        # Every event passes through here, mouse moves included, so anything that isn't a plain or Shift arrow
        # leaves at once.
        if direction is None or event.value != "PRESS" or event.ctrl or event.alt or event.oskey:
            return {"PASS_THROUGH"}
        region = _tree_region(context.window, event)
        if region is None:
            return {"PASS_THROUGH"}
        _TreeKeyboardWatcherState.step(context.window_manager, direction, event.shift)
        region.tag_redraw()
        return {"RUNNING_MODAL"}  # consumed: neither the list nor the Frames keymap sees it


def _start_watching() -> None:
    _TreeKeyboardWatcherState.watching = True
    wm: Any = bpy.context.window_manager
    for window in wm.windows:
        override: Any = bpy.context.temp_override(window=window)  # the stubs miss its context manager methods
        with override:
            bpy.ops.poc_sg.watch_keys("INVOKE_DEFAULT")  # ty: ignore[unresolved-attribute]


@persistent
def _on_load_post(_file: str) -> None:
    bpy.app.timers.register(_start_watching, first_interval=0.1)  # once the loaded file's windows exist


def register(step: Callable[[Any, str, bool], None], is_tree_region: Callable[[Any, Any], bool]) -> None:
    """Register the watcher and start it in every window; step moves through the tree."""
    _TreeKeyboardWatcherState.step = step
    _TreeKeyboardWatcherState.is_tree_region = is_tree_region
    bpy.utils.register_class(POC_SG_OT_watch_keys)
    bpy.app.handlers.load_post.append(_on_load_post)
    if not bpy.app.background:
        bpy.app.timers.register(_start_watching, first_interval=0.1)


def unregister() -> None:
    """Stop the watchers, and unregister."""
    _TreeKeyboardWatcherState.watching = False  # each watcher ends at its next event
    bpy.app.handlers.load_post.remove(_on_load_post)
    bpy.utils.unregister_class(POC_SG_OT_watch_keys)
