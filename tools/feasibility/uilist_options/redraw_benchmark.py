"""Time the scene graph widget's sidebar redraws with and without filter flags, in a window.

    Blender --factory-startup --python tools/feasibility/uilist_options/redraw_benchmark.py -- <case> <row count>

It hosts the widget in the 3D View's sidebar, on a generated stage of one group of leaves, expanded so the list has
<row count> rows, and redraws the sidebar as fast as Blender's event loop runs it: a timer that tags the region for
redraw on every tick. Once warm, it prints the time the panel's `draw` takes, which is when `template_list` calls
`filter_items` and each shown row's `draw_item`, and the time per tick, which the display's refresh rate can bound
from below. The cases:
- `empty`: the panel draws one label, for the loop's own time per tick.
- `widget`: the widget as it is, with no `filter_items`, so Blender filters the list itself.
- `reused_flags`: a `filter_items` that returns one list of flags, computed on its first call.
- `computed_flags`: a `filter_items` that computes each row's flags on every call, from the tree's rows: whether
  the row is the last of its parent's children, as the options demo's guide glyphs need.
"""

from __future__ import annotations

import importlib.util
import statistics
import sys
import time
from pathlib import Path
from typing import Any, override

import bpy

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from proscenium.ui.scene_graph_widget import display  # noqa: E402 (found through the path inserted above)
from proscenium.ui.scene_graph_widget.display import scene_graph_drawing, scene_graph_views  # noqa: E402

CASES = ("empty", "widget", "reused_flags", "computed_flags")
VIEW_NAME = "benchmark"
WARM_UP_SECONDS = 1.5
MEASURE_SECONDS = 4.0
LAST_SIBLING_BIT = 1 << 0


def _load_demo_module() -> Any:
    # tools/scene_graph_demo.py generates the stage; it isn't a package, so it's loaded from its path.
    spec = importlib.util.spec_from_file_location("scene_graph_demo", ROOT / "tools" / "scene_graph_demo.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BenchmarkState:
    """The case being run, the reused flags, and what the timer and panel counted."""

    case = "widget"
    reused_flags: list[int] = []  # noqa: RUF012 (class-level state)
    tick_times: list[float] = []  # noqa: RUF012
    panel_draw_durations_seconds: list[float] = []  # noqa: RUF012
    panel_draw_count = 0
    filter_call_count = 0
    started = 0.0
    draw_item_count = 0
    stage: Any = None  # the host holds the stage; the widget's views don't keep it alive


def _computed_flags(bitflag_filter_item: int) -> list[int]:
    view = scene_graph_views.scene_graph_view(VIEW_NAME)
    tree = view.prim_tree_view.tree
    rows = tree.rows if tree is not None else []
    flags = [bitflag_filter_item] * len(rows)
    has_later_sibling_at_depth: dict[int, bool] = {}
    for row_index in range(len(rows) - 1, -1, -1):
        depth = rows[row_index].depth
        if not has_later_sibling_at_depth.get(depth, False):
            flags[row_index] |= LAST_SIBLING_BIT
        has_later_sibling_at_depth[depth] = True
        for deeper in [d for d in has_later_sibling_at_depth if d > depth]:
            del has_later_sibling_at_depth[deeper]
    return flags


def _filter_items(self: Any, _context: Any, data: Any, property_name: str) -> tuple[Any, Any]:
    BenchmarkState.filter_call_count += 1
    if BenchmarkState.case == "computed_flags":
        return _computed_flags(self.bitflag_filter_item), []
    if len(BenchmarkState.reused_flags) != len(getattr(data, property_name)):
        BenchmarkState.reused_flags = _computed_flags(self.bitflag_filter_item)
    return BenchmarkState.reused_flags, []


class BenchmarkPanel(bpy.types.Panel):
    """The widget's tree, or one label for the empty case."""

    bl_idname = "VIEW3D_PT_uilist_redraw_benchmark"
    bl_label = "Redraw Benchmark"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Item"  # the sidebar's open tab, which scripts can't change

    @override
    def draw(self, context: Any) -> None:
        started = time.perf_counter()
        layout: Any = self.layout
        if BenchmarkState.case == "empty":
            layout.label(text="Empty")
        else:
            display.draw_tree(layout, context, VIEW_NAME)
        BenchmarkState.panel_draw_count += 1
        BenchmarkState.panel_draw_durations_seconds.append(time.perf_counter() - started)


def _sidebar() -> tuple[Any, Any]:
    wm: Any = bpy.context.window_manager
    window = wm.windows[0]
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    return area, next(r for r in area.regions if r.type == "UI")


def _tick() -> float | None:
    now = time.perf_counter()
    area, region = _sidebar()
    area.spaces.active.show_region_ui = True
    region.tag_redraw()
    elapsed = now - BenchmarkState.started
    if elapsed < WARM_UP_SECONDS:
        BenchmarkState.panel_draw_count = BenchmarkState.filter_call_count = BenchmarkState.draw_item_count = 0
        BenchmarkState.panel_draw_durations_seconds.clear()
        return 0.0
    BenchmarkState.tick_times.append(now)
    if elapsed < WARM_UP_SECONDS + MEASURE_SECONDS:
        return 0.0
    _report()
    bpy.ops.wm.quit_blender()
    return None


def _report() -> None:
    times = BenchmarkState.tick_times
    intervals_ms = [(b - a) * 1000 for a, b in zip(times, times[1:], strict=False)]
    draws_ms = [duration * 1000 for duration in BenchmarkState.panel_draw_durations_seconds]
    tree = scene_graph_views.scene_graph_view(VIEW_NAME).prim_tree_view.live_tree()
    row_count = len(tree.rows) if tree is not None else 0
    # Rows drawn per panel draw: zero, outside the empty case, means the list never drew.
    rows_per_draw = BenchmarkState.draw_item_count / max(BenchmarkState.panel_draw_count, 1)
    is_valid = BenchmarkState.case == "empty" or (tree is not None and rows_per_draw > 0)
    print(
        f"BENCHMARK{'' if is_valid else '_INVALID'} case={BenchmarkState.case} rows={row_count} "
        f"rows_drawn_per_draw={rows_per_draw:.1f} ticks={len(intervals_ms)} "
        f"panel_draws={BenchmarkState.panel_draw_count} filter_calls={BenchmarkState.filter_call_count} "
        f"draw_median_ms={statistics.median(draws_ms):.2f} draw_max_ms={max(draws_ms):.2f} "
        f"tick_median_ms={statistics.median(intervals_ms):.2f}"
    )


def main() -> None:
    """Host the widget on a generated stage, expand it to the row count, and start timing."""
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    BenchmarkState.case, leaf_count = arguments[0], int(arguments[1])
    if BenchmarkState.case not in CASES:
        raise SystemExit(f"case must be one of {CASES}")
    original_draw_item = scene_graph_drawing.SceneGraphList.draw_item

    # Blender checks a draw_item's parameter count, so the wrapper names them all.
    def counted_draw_item(  # noqa: PLR0913
        self: Any,
        context: Any,
        layout: Any,
        data: Any,
        item: Any,
        icon: Any,
        active_data: Any,
        active_property: Any,
        index: Any,
        flt_flag: Any,
    ) -> None:
        BenchmarkState.draw_item_count += 1
        original_draw_item(self, context, layout, data, item, icon, active_data, active_property, index, flt_flag)

    scene_graph_drawing.SceneGraphList.draw_item = counted_draw_item
    if BenchmarkState.case in {"reused_flags", "computed_flags"}:
        scene_graph_drawing.SceneGraphList.filter_items = _filter_items  # ty: ignore[invalid-assignment]
    display.register()
    bpy.utils.register_class(BenchmarkPanel)
    display.create_view(VIEW_NAME, lambda _area, _region: True)
    stage = _load_demo_module().synthetic_stage(fanout=0, depth=0, wide_leaf_count=leaf_count)
    BenchmarkState.stage = stage
    display.set_stage(VIEW_NAME, stage)
    tree = scene_graph_views.scene_graph_view(VIEW_NAME).prim_tree_view.tree
    assert tree is not None
    world_row_index = tree.row_index(stage.GetPrimAtPath("/World").GetPath())
    bpy.ops.proscenium.scene_graph_toggle_row(view_name=VIEW_NAME, row_index=world_row_index)  # ty: ignore[unresolved-attribute]
    wide_row_index = tree.row_index(stage.GetPrimAtPath("/World/Wide").GetPath())
    bpy.ops.proscenium.scene_graph_toggle_row(view_name=VIEW_NAME, row_index=wide_row_index)  # ty: ignore[unresolved-attribute]
    BenchmarkState.started = time.perf_counter()
    bpy.app.timers.register(_tick, first_interval=0.5)


if __name__ == "__main__":
    main()
