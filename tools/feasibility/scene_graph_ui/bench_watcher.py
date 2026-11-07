"""Windowed benchmark: what the key watcher, and other modal operators like it, cost per event.

Run in the Blender binary (simulated events need the flag):

    Blender --factory-startup --enable-event-simulate --python tools/feasibility/scene_graph_ui/bench_watcher.py

Each trial queues a batch of simulated mouse moves over the 3D View and times how long the window takes to handle
them, from queueing them to a timer that runs once they're handled. A trial runs with no modal operator, with
pass-through modal operators that return at once (stand-ins for other add-ons'), or with the tree's watcher among
them. One stand-in, added first so it runs last, counts the events, which checks that the timer ran after all of
them. Configurations take turns, so drift in the machine's speed spreads across all of them.
"""

from __future__ import annotations

import pathlib
import statistics
import sys
import time
import traceback
from typing import TYPE_CHECKING, Any, override

import bpy

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import addon  # noqa: E402 (found through the path inserted above when run as a script)
import tree_keys  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

EVENTS = 2000  # mouse moves per trial
TRIALS = 7  # per configuration
# (label, the tree's watcher, stand-ins): the counting stand-in is one of them wherever there are any.
CONFIGS: tuple[tuple[str, bool, int], ...] = (
    ("none", False, 0),
    ("1 stand-in", False, 1),
    ("1 stand-in + tree watcher", True, 1),
    ("10 stand-ins", False, 10),
    ("10 stand-ins + tree watcher", True, 10),
    ("50 stand-ins", False, 50),
)


class _Stats:
    running = False  # cleared to end the stand-ins at their next event
    counted = 0  # events the counting stand-in has seen
    watcher_ns = 0  # time spent in the tree watcher's modal, in Python
    watcher_calls = 0


class POC_SG_OT_stand_in(bpy.types.Operator):  # noqa: N801 - Blender's class naming
    """A modal operator that passes every event on: the least another add-on's could cost."""

    bl_idname = "poc_sg.stand_in"
    bl_label = "Stand-in Modal"
    bl_options = {"INTERNAL"}

    counts: bpy.props.BoolProperty()  # ty: ignore[invalid-type-form]

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    @override
    def modal(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        if not _Stats.running:
            return {"CANCELLED", "PASS_THROUGH"}  # without PASS_THROUGH, the event would end only this one
        if self.counts:
            _Stats.counted += 1
        return {"PASS_THROUGH"}


def _timed(modal: Callable[..., Any]) -> Callable[..., Any]:
    # Blender looks a modal method up on the class at each call, so a wrapper set after registering is used.
    def timed(self: Any, context: Any, event: Any) -> Any:
        start = time.perf_counter_ns()
        result = modal(self, context, event)
        _Stats.watcher_ns += time.perf_counter_ns() - start
        _Stats.watcher_calls += 1
        return result

    return timed


def _invoke(window: Any, operator: Callable[..., Any], **properties: Any) -> None:
    override: Any = bpy.context.temp_override(window=window)  # the stubs miss its context manager methods
    with override:
        operator("INVOKE_DEFAULT", **properties)


def _viewport(window: Any) -> Any:
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    return next(region for region in area.regions if region.type == "WINDOW")


def _queue_moves(window: Any, count: int) -> None:
    region = _viewport(window)
    for i in range(count):
        # Back and forth across the viewport, so each event is a real move.
        x = region.x + region.width // 4 + (i % 50) * 8
        window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=region.y + region.height // 2)


def _start(window: Any, watcher: bool, stand_ins: int) -> None:
    _Stats.running = True
    tree_keys._State.watching = watcher  # noqa: SLF001 - the bench starts and ends the watcher itself
    for i in range(stand_ins):
        _invoke(window, bpy.ops.poc_sg.stand_in, counts=i == 0)  # ty: ignore[unresolved-attribute]
    if watcher:
        _invoke(window, bpy.ops.poc_sg.watch_keys)  # ty: ignore[unresolved-attribute]


def _stop(window: Any) -> None:
    _Stats.running = False
    tree_keys._State.watching = False  # noqa: SLF001
    _queue_moves(window, 1)  # each modal operator ends at its next event


def _bench() -> Iterator[float]:
    """The benchmark's steps; each yield waits that many seconds, in a timer, before the next step."""
    wm: Any = bpy.context.window_manager  # never None while Blender runs timers
    window: Any = wm.windows[0]
    watcher: Any = tree_keys.POC_SG_OT_watch_keys
    watcher.modal = _timed(watcher.modal)
    tree_keys._State.watching = False  # noqa: SLF001 - ends the watcher the add-on started
    _queue_moves(window, 1)
    yield 0.5
    times: dict[str, list[float]] = {label: [] for label, _, _ in CONFIGS}
    for trial in range(TRIALS + 1):  # the first round warms up, and isn't kept
        for label, watcher, stand_ins in CONFIGS:
            _start(window, watcher, stand_ins)
            yield 0.2
            _Stats.counted = 0
            start = time.perf_counter()
            _queue_moves(window, EVENTS)
            yield 0.0
            elapsed = time.perf_counter() - start
            if stand_ins and _Stats.counted != EVENTS:
                print(f"  {label}: the timer ran after {_Stats.counted} of {EVENTS} events", flush=True)
            if trial:
                times[label].append(elapsed)
            _stop(window)
            yield 0.2
    base = statistics.median(times["none"])
    print(f"\n{EVENTS} mouse moves per trial, median of {TRIALS} trials", flush=True)
    print(f"{'configuration':<30}{'batch ms':>10}{'µs/event':>10}{'added µs/event':>16}", flush=True)
    for label, _, _ in CONFIGS:
        median = statistics.median(times[label])
        spread = f"{min(times[label]) * 1000:.0f}-{max(times[label]) * 1000:.0f}"
        added = (median - base) / EVENTS * 1e6
        print(f"{label:<30}{median * 1000:>10.1f}{median / EVENTS * 1e6:>10.1f}{added:>16.1f}  ({spread})", flush=True)
    calls = _Stats.watcher_calls
    print(f"tree watcher's modal in Python: {_Stats.watcher_ns / max(calls, 1) / 1000:.2f} µs/call, {calls} calls")

    # Unregistering while the watcher runs: Blender is expected to drop the operator's handlers with its type.
    tree_keys._State.watching = True  # noqa: SLF001
    _invoke(window, bpy.ops.poc_sg.watch_keys)  # ty: ignore[unresolved-attribute]
    yield 0.2
    addon.unregister()
    _queue_moves(window, 20)
    window.event_simulate(type="RIGHT_ARROW", value="PRESS", x=10, y=10)
    window.event_simulate(type="RIGHT_ARROW", value="RELEASE", x=10, y=10)
    yield 0.5
    print("unregistered while watching, then 20 moves and a key: still running", flush=True)


def _driver(steps: Iterator[float]) -> Callable[[], float | None]:
    def run() -> float | None:
        try:
            return next(steps)
        except StopIteration:
            pass
        except Exception:  # noqa: BLE001 - report, then quit, so a failed run doesn't hang
            traceback.print_exc()
        sys.stdout.flush()
        bpy.ops.wm.quit_blender()
        return None

    return run


if __name__ == "__main__":
    bpy.utils.register_class(POC_SG_OT_stand_in)
    addon.register()
    bpy.app.timers.register(_driver(_bench()), first_interval=1.5)
