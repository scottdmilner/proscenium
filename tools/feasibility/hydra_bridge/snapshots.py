"""Per-time-code snapshots (M4 Phase E, E2): a display that follows the frame by synchronizing at each one.

A frame step is a synchronization at the frame's time code through the update path: an incremental capture, a
plan reusing the previous plan's mesh builds (D9), the plan diff, and an update by it, with update.py, or
batch_update.py for the batched display, under a user policy and with or without moves, which keep an object whose
transform changed and set its matrix. The display holds no animation data: what it shows at a frame is what
synchronizing at that time code gives. `follow` steps it from a frame-change handler, so playback is one step per
frame. A frame's time code is its frame number, subframe included.
"""

from __future__ import annotations

import time as clock
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import batch
import batch_update
import bpy
import update
from apply import apply

if TYPE_CHECKING:
    from collections.abc import Callable

    from plan_types import Plan, PlanDiff


@dataclass
class Step:
    """One frame step: its time code, the plan and diff it updated by, what the update wrote, and its stages."""

    time: float
    plan: Plan
    diff: PlanDiff
    prepared: Any  # update.Prepared, or batch_update.Prepared
    seconds: dict[str, float] = field(default_factory=dict)  # by stage: capture, planning, diff, prepare, ...


class Snapshots:
    """A display of `stage` in `collection`, synchronized at `time` and then at each time code it steps to."""

    native: Any
    bridge: Any
    plan: Plan
    display: Any  # apply.Display, or batch.BatchedDisplay
    collection: bpy.types.Collection
    batched: bool
    users: update.UserPolicy
    moves: bool  # whether updates keep moved objects and set their matrices
    settings: dict[str, Any]  # build_plan's settings
    last: Step | None  # the latest step, None before the first

    def __init__(  # noqa: PLR0913 - the source, the destination, and how it is displayed
        self,
        native: Any,
        stage: Any,
        collection: bpy.types.Collection,
        time: float,
        representation: str = "objects",
        users: update.UserPolicy = update.UserPolicy.REPOINT,
        moves: bool = False,
        minimum: int = batch.MINIMUM,
        **settings: Any,
    ) -> None:
        """Batched, copies alike but for their placement batch in groups of at least `minimum`."""
        self.native = native
        self.users = users
        self.moves = moves
        self.bridge = native.Bridge(stage)
        self.settings = settings
        self.plan = native.build_plan(self.bridge.capture(time), **settings)
        self.collection = collection
        self.batched = representation == "batched"
        self.display = (
            batch.apply_batched(self.plan, collection, minimum) if self.batched else apply(self.plan, collection)
        )
        self.last = None

    def step(self, time: float) -> Step:
        """Synchronize at `time` by updating the display from the published plan's diff."""
        seconds: dict[str, float] = {}

        def timed[T](name: str, call: Callable[[], T]) -> T:
            start = clock.perf_counter()
            result = call()
            seconds[name] = clock.perf_counter() - start
            return result

        updater: Any = batch_update if self.batched else update
        snapshot = timed("capture", lambda: self.bridge.capture(time, incremental=True))
        plan = timed("planning", lambda: self.native.build_plan(snapshot, previous=self.plan, **self.settings))
        diff = timed("diff", lambda: self.native.diff_plans(self.plan, plan))
        prepared = timed("prepare", lambda: updater.prepare(plan, diff, self.display, self.users, self.moves))
        self.display = timed("publish", lambda: updater.publish(prepared, self.display, self.collection))
        timed("retire", lambda: updater.retire(prepared))
        self.plan = plan
        self.last = Step(time, plan, diff, prepared, seconds)
        return self.last

    def follow(self, scene: bpy.types.Scene) -> Callable[..., None]:
        """Step to `scene`'s frame at each frame change, before Blender evaluates it; returns the handler installed.

        Remove it from bpy.app.handlers.frame_change_pre to stop following.
        """

        def on_frame(changed: bpy.types.Scene, _depsgraph: Any = None) -> None:
            if changed == scene:
                self.step(changed.frame_current + changed.frame_subframe)

        bpy.app.handlers.frame_change_pre.append(on_frame)
        return on_frame

    def release(self) -> None:
        self.bridge.release()
