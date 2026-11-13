"""The scene graph widget's arrow keys in a window, from simulated events (tests/isolated/test_scene_graph_keys.py).

Each body is a generator the windowed runner steps through (runner.py): a step simulates mouse moves and key
presses, and the wait it yields lets the window handle them and redraw. The views are hosted in a Properties editor,
which the window's largest area becomes, maximized to fill the window, in panels on its Scene tab. Blender's own
panels there are unregistered first, since they draw ahead of any add-on's and would push the views' panels off a
short window; the process is the test's alone. The rows are found by moving the cursor down the editor and reading
which list row Blender says is under it, so the tests depend on neither the window's size nor its scale, so long as
the panels fit in it. Blender's objects are typed `Any` here, as the stubs make every context member optional.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, NamedTuple

import bpy
from pxr import Sdf, Usd

from proscenium.ui.columned_list import column_layout
from proscenium.ui.scene_graph_widget import display
from proscenium.ui.scene_graph_widget.display import list_columns, scene_graph_properties, scene_graph_views

if TYPE_CHECKING:
    from collections.abc import Generator

    Steps = Generator[float, None, Any]

STEP_SECONDS = 0.05  # each step's wait, for the window to handle the step's events and redraw
SETTLE_SECONDS = 0.5  # after a view is shown or the widget registered: its watcher starts 0.1 s after registration
SWEEP_STEP_PIXELS = 6  # the cursor's step down the editor while finding the rows: under half a row at any scale
# Below a view's panel, by more than its bottom margin: the empty editor, where no list takes the arrow keys.
CLEAR_OF_PANELS_UNITS = 2.0
# A view's property, by the view's index in the window manager's views: over a list row, its active row.
VIEW_PROPERTY_PATH = re.compile(r"proscenium_scene_graph_views\[(\d+)\]\.(\w+)$")
FIRST_ROW_PATH = "/_Crate"  # prim_kinds.usda's first top-level row, where Right with nothing selected lands


class Hovered(NamedTuple):
    """What a height of the editor has under the cursor."""

    y: int  # in the window's pixels, up from its bottom
    view_name: str | None  # the view whose properties hold the hovered button's, if a view's do
    is_row: bool  # whether that's a list row, whose property is its list's active row


def _make_properties_editor() -> None:
    """Make the window's largest area a Properties editor on its Scene tab, filling the window.

    None of Blender's own panels are left on the tab.
    """
    wm: Any = bpy.context.window_manager
    window = wm.windows[0]
    area = max(window.screen.areas, key=lambda area: area.width * area.height)
    area.type = "PROPERTIES"
    area.spaces.active.context = "SCENE"
    override: Any = bpy.context.temp_override(window=window, area=area)
    with override:
        bpy.ops.screen.screen_full_area()  # Ctrl+Space: the window's screen becomes this editor alone
    scene_panels = [
        panel
        for panel in _panel_classes(bpy.types.Panel)
        if getattr(panel, "bl_space_type", "") == "PROPERTIES" and getattr(panel, "bl_context", "") == "scene"
    ]
    for panel in sorted(scene_panels, key=lambda panel: not getattr(panel, "bl_parent_id", "")):  # children first
        if panel.is_registered:
            bpy.utils.unregister_class(panel)


def _panel_classes(base: Any) -> list[Any]:
    found: list[Any] = []
    for panel in base.__subclasses__():
        found.extend([panel, *_panel_classes(panel)])
    return found


def _properties_editor() -> tuple[Any, Any, Any]:
    """The window, its Properties editor, maximized, and the editor's main region, with the panels."""
    wm: Any = bpy.context.window_manager
    window = wm.windows[0]
    (area,) = window.screen.areas  # the maximized editor's screen
    region = next(region for region in area.regions if region.type == "WINDOW")
    return window, area, region


def _in_properties_editor(area: Any, region: Any) -> bool:
    return area.type == "PROPERTIES" and region.type == "WINDOW"


def _show_views(stage: Usd.Stage, view_names: list[str], selections: dict[str, list[str | None]]) -> list[Any]:
    """Register the widget, and show each view, with no columns, in a panel of its own, in order down the editor."""
    display.register()
    wm = bpy.context.window_manager
    panels: list[Any] = []
    for order, name in enumerate(view_names):
        selections.setdefault(name, [])
        display.create_view(name, _in_properties_editor, _hear_selections(selections[name]))
        display.set_stage(name, stage)
        properties = scene_graph_properties.view_properties(wm, name)
        for column in list_columns.COLUMNS:  # the name column then fills each row, where the cursor sweeps
            setattr(properties, column.show_property, False)
        panel = type(
            f"PROSCENIUM_TEST_PT_scene_graph_{name}",
            (bpy.types.Panel,),
            {
                "bl_space_type": "PROPERTIES",
                "bl_region_type": "WINDOW",
                "bl_context": "scene",
                "bl_label": f"Scene Graph {name}",
                "bl_order": order,
                "draw": _draw_tree_of(name),
            },
        )
        bpy.utils.register_class(panel)
        panels.append(panel)
    return panels


def _hear_selections(heard: list[str | None]) -> Any:
    def on_selection_changed(path: Sdf.Path | None) -> None:
        heard.append(_path_text(path))

    return on_selection_changed


def _draw_tree_of(view_name: str) -> Any:
    # A panel's draw takes exactly (self, context), so the view's name is bound here.
    def draw(self: Any, context: Any) -> None:
        display.draw_tree(self.layout, context, view_name, list_rows=4)

    return draw


def _hide_views(panels: list[Any]) -> None:
    for panel in panels:
        bpy.utils.unregister_class(panel)
    display.unregister()


def _path_text(path: Sdf.Path | None) -> str | None:
    return str(path) if path is not None else None


def _hovered(window: Any, area: Any, region: Any, y: int) -> Hovered:
    override: Any = bpy.context.temp_override(window=window, area=area, region=region)
    with override:
        hovered: Any = bpy.context.property
    found = (
        VIEW_PROPERTY_PATH.match(hovered[1]) if hovered and isinstance(hovered[0], bpy.types.WindowManager) else None
    )
    if found is None:
        return Hovered(y, None, is_row=False)
    view_name = hovered[0].proscenium_scene_graph_views[int(found[1])].name
    return Hovered(y, view_name, is_row=found[2] == "active_row_index")


def _sweep(window: Any, area: Any, region: Any, view_names: list[str]) -> Steps:
    """Move the cursor down the editor until it has passed every view's list and the search box below it.

    Returns the cursor's x and what each height had under it, top down.
    """
    x = region.x + region.width * 3 // 5  # past the names, so over the row itself
    hovered_by_height: list[Hovered] = []
    for y in range(region.y + region.height - SWEEP_STEP_PIXELS, region.y, -SWEEP_STEP_PIXELS):
        window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
        yield STEP_SECONDS
        hovered_by_height.append(_hovered(window, area, region, y))
        if all(_has_passed_list(hovered_by_height, name) for name in view_names):
            break
    return x, hovered_by_height


def _has_passed_list(hovered_by_height: list[Hovered], view_name: str) -> bool:
    """Whether the cursor has found a view's rows and then its search box, which is below its list."""
    row_indices = [index for index, each in enumerate(hovered_by_height) if each.view_name == view_name and each.is_row]
    return bool(row_indices) and any(
        each.view_name == view_name and not each.is_row for each in hovered_by_height[row_indices[-1] :]
    )


def _first_row_height(hovered_by_height: list[Hovered], view_name: str) -> int:
    """The height of a view's first row: the topmost the cursor found it at."""
    heights = [each.y for each in hovered_by_height if each.view_name == view_name and each.is_row]
    assert heights, f"the cursor found no row of {view_name}: {hovered_by_height}"
    return heights[0]


def _height_clear_of_panels(region: Any, hovered_by_height: list[Hovered]) -> int:
    """A height at the editor's bottom, clear of the views' panels: below one, its list still takes the arrow keys."""
    lowest_control_y = min(each.y for each in hovered_by_height if each.view_name is not None)
    bottom_y = region.y + SWEEP_STEP_PIXELS
    clearance = CLEAR_OF_PANELS_UNITS * column_layout.unit_pixels(bpy.context)
    assert lowest_control_y - bottom_y > clearance, "the editor is too short to have room below its panels"
    return bottom_y


def _press_right(window: Any, x: int, y: int) -> Steps:
    window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
    yield STEP_SECONDS
    window.event_simulate(type="RIGHT_ARROW", value="PRESS", x=x, y=y)
    window.event_simulate(type="RIGHT_ARROW", value="RELEASE", x=x, y=y)
    yield STEP_SECONDS


def _selected_paths(view_names: list[str]) -> dict[str, str | None]:
    return {name: _path_text(display.selected_path(name)) for name in view_names}


def _expanded_paths(view_names: list[str]) -> dict[str, list[str]]:
    """Each view's expanded rows: a step Right expands a row, where the list's own Right only selects the next."""
    expanded: dict[str, list[str]] = {}
    for name in view_names:
        tree = scene_graph_views.scene_graph_view(name).prim_tree_view.tree
        expanded[name] = sorted(str(path) for path in tree.expanded_paths) if tree is not None else []
    return expanded


def _heard(selections: dict[str, list[str | None]]) -> dict[str, list[str | None]]:
    """What each view's host has heard so far, copied, as later presses add to it."""
    return {name: list(heard) for name, heard in selections.items()}


def keys_step_the_hovered_view(stage_path: str) -> Steps:
    """Two views in one editor: Right over each one's row, then below both, where no list is under the cursor."""
    _make_properties_editor()
    yield STEP_SECONDS
    stage = Usd.Stage.Open(stage_path)
    view_names = ["first", "second"]
    selections: dict[str, list[str | None]] = {}
    _show_views(stage, view_names, selections)
    yield SETTLE_SECONDS
    window, area, region = _properties_editor()
    x, hovered_by_height = yield from _sweep(window, area, region, view_names)
    first_y, second_y = (_first_row_height(hovered_by_height, name) for name in view_names)
    below_y = _height_clear_of_panels(region, hovered_by_height)
    observed: dict[str, Any] = {"first_row_path": FIRST_ROW_PATH}
    yield from _press_right(window, x, second_y)
    observed["after_second"] = {
        "selected": _selected_paths(view_names),
        "expanded": _expanded_paths(view_names),
        "heard": _heard(selections),
    }
    yield from _press_right(window, x, first_y)
    observed["after_first"] = {
        "selected": _selected_paths(view_names),
        "expanded": _expanded_paths(view_names),
        "heard": _heard(selections),
    }
    scene: Any = bpy.context.scene
    frame_before = scene.frame_current
    yield from _press_right(window, x, below_y)
    observed["below"] = {
        "selected": _selected_paths(view_names),
        "frame_change": scene.frame_current - frame_before,
    }
    return observed


def keys_step_after_registering_again(stage_path: str) -> Steps:
    """One view: Right steps it, and still does once the widget has been unregistered and registered again."""
    _make_properties_editor()
    yield STEP_SECONDS
    stage = Usd.Stage.Open(stage_path)
    view_names = ["only"]
    selections: dict[str, list[str | None]] = {}
    panels = _show_views(stage, view_names, selections)
    yield SETTLE_SECONDS
    window, area, region = _properties_editor()
    x, hovered_by_height = yield from _sweep(window, area, region, view_names)
    row_y = _first_row_height(hovered_by_height, "only")
    yield from _press_right(window, x, row_y)
    before = {"selected": _selected_paths(view_names), "expanded": _expanded_paths(view_names)}
    _hide_views(panels)
    yield SETTLE_SECONDS
    _show_views(stage, view_names, selections)  # a new view, so nothing is selected again
    yield SETTLE_SECONDS
    yield from _press_right(window, x, row_y)  # the same layout, so the row is where it was
    after = {"selected": _selected_paths(view_names), "expanded": _expanded_paths(view_names)}
    return {"before": before, "after": after, "heard": selections}
