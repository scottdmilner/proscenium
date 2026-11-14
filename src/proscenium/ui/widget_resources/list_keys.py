"""Left and Right arrow keys for widgets' lists, taken by a modal operator before a UIList sees them.

Over a list, the UIList's own handler takes all four arrow keys to move its active row, ahead of every keymap, and
its update callback can't tell which key moved it. A modal operator's handler runs before the regions' handlers, so
it sees each event first: it takes Left and Right (and Shift with them) while the cursor is over a region a list's
host says is showing that list, and in a region showing several, over a row of that list; it passes every other event
on. Up and Down stay with the list.

The watcher serves every widget: each widget adds its lists (`KeyedLists`), and a list says where it shows, whether
the hovered row is its own, and how a key steps it (`KeyedList`). One widget's step is its own, as a tree's expands a
row and a property list's shows a property's targets.

It runs before a text field being edited, too, and Blender doesn't tell Python when one is. So a widget marks a list
whose search text is being typed as not steppable, and the watcher leaves Left and Right to the text box until a key
that ends a text edit (ENDING_EDIT_KEYS), which it tells each widget.

A modal operator is per window, so each window gets its own watcher: one starts in every window once the first
widget's lists are added, and drawing a list starts one in any window whose running modal operators don't include
one, such as a window opened since, every window after a file load ends them all, or every window after the widgets
are registered again, since unregistering the operator ends each watcher. Every event reaches every modal operator,
so the watcher returns at once from any it doesn't take.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, override

import bpy

from ..widget_model.list_steps import StepDirection

if TYPE_CHECKING:
    from collections.abc import Callable

    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

KEY_DIRECTIONS = {"RIGHT_ARROW": StepDirection.INTO, "LEFT_ARROW": StepDirection.OUT_OF}
ENDING_EDIT_KEYS = frozenset({"RET", "NUMPAD_ENTER", "ESC", "TAB"})
START_DELAY_SECONDS = 0.1  # after registration, once the windows exist
WATCHER_RUNNING_IDNAME = "PROSCENIUM_OT_watch_list_keys"  # how a window's modal operators name a watcher


@dataclass(frozen=True, slots=True)
class KeyedList:
    """One list the watcher steps: where it shows, whether the hovered row is its, and what a key does to it."""

    # (area, region) -> whether the region is drawing the list now, as its host says.
    shows_in_region: Callable[[Any, Any], bool]
    # Whether a hovered property, as `context.property` gives one, is this list's: over a row, its active row.
    holds_property: Callable[[Any], bool]
    # Whether a key steps the list now: it shows something, and its search text isn't being typed.
    is_steppable: Callable[[], bool]
    # Steps the list in a direction, with Shift or not, and syncs it and tells its host.
    step: Callable[[StepDirection, bool], None]


@dataclass(frozen=True, slots=True)
class KeyedLists:
    """A widget's lists the watcher steps, and how the widget ends their search text's typing."""

    lists: Callable[[], list[KeyedList]]  # the widget's lists now, in the order it added them
    stop_entering_search_text: Callable[[], None]  # after a key that ends a text edit


class _ListKeysState:
    """The widgets' lists, while added, and whether the watchers should keep running."""

    keyed_lists: list[KeyedLists] = []
    is_watching = False  # cleared to end every watcher at its next event


def item_name_holding(hovered_property: Any, collection_property: str) -> str | None:
    """The name of the window manager's collection item holding a hovered property, or None.

    The hovered property is `context.property`'s (owner, data path, index); over a list, it's its row's active index,
    a property of the list's item, so this names the list under the cursor.
    """
    if not hovered_property:
        return None
    owner, data_path, _array_index = hovered_property
    if not isinstance(owner, bpy.types.WindowManager):
        return None
    found = re.match(rf"{re.escape(collection_property)}\[(\d+)\]\.", data_path)
    if found is None:
        return None
    items = getattr(owner, collection_property)
    item_index = int(found[1])
    return items[item_index].name if item_index < len(items) else None


def _contains(rect: Any, event: Any) -> bool:
    return rect.x <= event.mouse_x < rect.x + rect.width and rect.y <= event.mouse_y < rect.y + rect.height


def _all_lists() -> list[KeyedList]:
    return [keyed_list for keyed_lists in _ListKeysState.keyed_lists for keyed_list in keyed_lists.lists()]


def _hovered_property(window: Any, area: Any, region: Any) -> Any:
    # The watcher's own context has no region, so it reads the region's hovered button through an override.
    override: Any = bpy.context.temp_override(window=window, area=area, region=region)
    with override:
        return getattr(bpy.context, "property", None)


def _list_under_cursor(window: Any, event: Any) -> tuple[KeyedList, Any] | None:
    """The list whose host draws it under the cursor, and the region it's in.

    In a region showing several lists, it's the one whose row is under the cursor, or None between them.
    """
    area = next((area for area in window.screen.areas if _contains(area, event)), None)
    if area is None:
        return None
    # A 3D View's sidebar overlaps its main region, so any region under the cursor that shows a list counts.
    for region in area.regions:
        if not _contains(region, event):
            continue
        shown = [keyed_list for keyed_list in _all_lists() if keyed_list.shows_in_region(area, region)]
        if len(shown) == 1:
            return shown[0], region
        if shown:
            # Over a row, the hovered property is its list's active row; over a button in it, none is, so the key
            # passes on rather than step a list that may not be the one under the cursor.
            hovered = _hovered_property(window, area, region)
            keyed_list = next((keyed_list for keyed_list in shown if keyed_list.holds_property(hovered)), None)
            return (keyed_list, region) if keyed_list is not None else None
    return None


def _has_watcher(window: Any) -> bool:
    # A window lists its running modal operators by their C-style idnames; an ended one's entry reads None.
    return any(
        operator is not None and operator.bl_idname == WATCHER_RUNNING_IDNAME for operator in window.modal_operators
    )


class WatchListKeys(bpy.types.Operator):
    """Take Left and Right over a widget's list before its UIList does."""

    bl_idname = "proscenium.watch_list_keys"
    bl_label = "Watch List Keys"
    bl_options = {"INTERNAL"}

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        if _has_watcher(context.window):
            return {"CANCELLED"}
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    @override
    def modal(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        if not _ListKeysState.is_watching:
            return {"CANCELLED", "PASS_THROUGH"}  # without PASS_THROUGH, ending would consume the event
        if event.type in ENDING_EDIT_KEYS and event.value == "PRESS":
            stop_entering_search_text()
            return {"PASS_THROUGH"}
        direction = KEY_DIRECTIONS.get(event.type)
        if direction is None or event.value != "PRESS" or event.ctrl or event.alt or event.oskey:
            return {"PASS_THROUGH"}
        found = _list_under_cursor(context.window, event)
        if found is None or not found[0].is_steppable():
            return {"PASS_THROUGH"}  # for the search's text box, or Blender's own keys
        keyed_list, region = found
        keyed_list.step(direction, event.shift)
        region.tag_redraw()
        return {"RUNNING_MODAL"}  # consumed: neither the list nor the Frames keymap sees it


def _start_missing_watchers() -> None:
    # A timer, so it returns None: a draw can't invoke an operator, so it schedules this.
    wm: Any = bpy.context.window_manager
    if not _ListKeysState.is_watching or wm is None:
        return
    for window in wm.windows:
        if _has_watcher(window):
            continue
        override: Any = bpy.context.temp_override(window=window)  # the stubs miss its context manager methods
        with override:
            bpy.ops.proscenium.watch_list_keys("INVOKE_DEFAULT")  # ty: ignore[unresolved-attribute]


def _schedule_start(delay_seconds: float) -> None:
    # Nothing in background mode, which has no windows.
    if not bpy.app.background and not bpy.app.timers.is_registered(_start_missing_watchers):
        bpy.app.timers.register(_start_missing_watchers, first_interval=delay_seconds)


def add_keyed_lists(keyed_lists: KeyedLists) -> None:
    """Add a widget's lists for the watchers to step, starting a watcher in every window once the windows exist."""
    _ListKeysState.keyed_lists.append(keyed_lists)
    if not _ListKeysState.is_watching:
        _ListKeysState.is_watching = True
        _schedule_start(START_DELAY_SECONDS)


def remove_keyed_lists(keyed_lists: KeyedLists) -> None:
    """Remove a widget's lists; once no widget's are left, end every watcher at its next event."""
    _ListKeysState.keyed_lists.remove(keyed_lists)
    if not _ListKeysState.keyed_lists:
        _ListKeysState.is_watching = False
        if bpy.app.timers.is_registered(_start_missing_watchers):
            bpy.app.timers.unregister(_start_missing_watchers)


def ensure_watcher(window: Any) -> None:
    """Start a watcher in a window that draws a list, if the watchers are running and it has none."""
    if _ListKeysState.is_watching and window is not None and not _has_watcher(window):
        _schedule_start(0.0)


def stop_entering_search_text() -> None:
    """Tell every widget a text edit has ended, as after Enter, Esc, Tab, or a file load."""
    for keyed_lists in _ListKeysState.keyed_lists:
        keyed_lists.stop_entering_search_text()


# In registration order.
CLASSES = (WatchListKeys,)
