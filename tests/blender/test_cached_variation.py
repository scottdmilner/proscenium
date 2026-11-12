"""What a cache call keys: the copies that vary, found by comparing plans (M7 plan, D1).

DECISIONS.md "What a cache call keys". A cache call compares the plan at each time code it caches with the generation's
own, held since it was published, and keys the copies a time code moves, at every time code the generation holds: one
keyed for the first time is keyed with the value it showed at the generation's own time code and at those cached before,
where it didn't differ. A copy equal everywhere has no keys. Without the generation's plan held, every copy is keyed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import edit_sequence, incremental
from proscenium.binding.results import ResultState
from support.refresh_checks import copy_object, entries_by_source

if TYPE_CHECKING:
    from pathlib import Path

    from pxr import Usd

    from proscenium.api.bindings import BindingHandle, Bindings


def _synchronized(bindings: Bindings, stage: Usd.Stage, time_code: float = 0.0) -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
    assert handle.attach(stage).state is not ResultState.FATAL_FAILURE
    assert handle.synchronize(time_code).state is not ResultState.FATAL_FAILURE
    return handle


def _animated(handle: BindingHandle) -> set[str]:
    """The source entities of the copies whose objects hold an action."""
    return {
        source
        for source, entries in entries_by_source(handle.binding_id).items()
        if (animation := copy_object(entries).animation_data) is not None and animation.action is not None
    }


def test_only_the_copies_that_vary_are_keyed(bindings: Bindings, tmp_path: Path) -> None:
    # CACHE-01 on F-EDIT-SEQUENCE: cached at 5 and 10, only Mover, whose translate is sampled, is keyed.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        assert handle.cache(scene.cached_time_codes).state is not ResultState.FATAL_FAILURE
        assert _animated(handle) == {source for source, _ in scene.keyed_copies}


@pytest.mark.parametrize("calls", [(30.0, 15.0), (15.0, 30.0)], ids=["equal-first", "differing-first"])
def test_each_frame_shows_its_time_code_whichever_call_keyed_it(
    bindings: Bindings, tmp_path: Path, calls: tuple[float, float]
) -> None:
    # CACHE-01, CACHE-09 on F-SAME-VALUES, synchronized at 0, where Held is at 0 as at 30, and at 5 at 15, cached by
    # one call for each: 30 first keys nothing, and 15 after keys Held at 0 and 30 too, with the value it showed there;
    # 15 first keys Held, and 30 after keys it again, since it is keyed, though equal there. Either way each frame
    # shows the latest time code at or before it.
    with incremental.same_values(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        for time_code in calls:
            assert handle.cache([time_code]).state is ResultState.SUCCESS
            assert (incremental.HELD in _animated(handle)) == (time_code == 15.0 or calls[0] == 15.0), time_code
        held = copy_object(entries_by_source(handle.binding_id)[incremental.HELD])
        target = bpy.data.scenes["Scene"]
        for frame, time_code in ((0, 0.0), (15, 15.0), (20, 15.0), (30, 30.0)):
            target.frame_set(frame)
            assert held.matrix_world.translation.x == pytest.approx(scene.held_x(time_code)), frame


def test_without_the_generations_plan_every_copy_is_keyed(bindings: Bindings, tmp_path: Path) -> None:
    # Without the plan the generation was published with, as after an undo past the held plans, a call can't tell
    # what varies, so it keys every copy.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        bindings.published_plans.release(handle.binding_id)
        assert handle.cache(scene.cached_time_codes).state is not ResultState.FATAL_FAILURE
        assert _animated(handle) == set(entries_by_source(handle.binding_id))
