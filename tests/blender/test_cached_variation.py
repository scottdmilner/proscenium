"""What a cache call keys: the copies that vary, found by comparing plans (M7 plan, D1).

DECISIONS.md "What a cache call keys". A cache call compares the plan at each time code it caches with the generation's
own, held since it was published, and keys the copies a time code moves, at every time code the generation holds: one
keyed for the first time is keyed with the value it showed at the generation's own time code and at those cached before,
where it didn't differ. A copy equal everywhere has no keys. Without the generation's plan held, every copy is keyed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest

from fixtures import edit_sequence, incremental, time_variations
from proscenium.binding.results import ResultState
from proscenium.synchronization import time_code_keying
from support.clean_rebuild import clean_rebuild
from support.displayed_copies import displayed_copies
from support.refresh_checks import copy_object, entries_by_source

from .published_state import datablocks, published_generation

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from pxr import Usd

    from proscenium.api.bindings import BindingHandle, Bindings
    from support.bounds_check import DisplayedCopy


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


# F-TIME-VARIATIONS' copies whose transform, visibility, or shear varies, and Still, which doesn't (M7 plan, D2).
_TRANSFORMED = (time_variations.MOVER, time_variations.BLINK, time_variations.SKEW, time_variations.SHEARING)
_SHOWN = (*_TRANSFORMED, time_variations.STILL)
type _Shown = tuple[bool, bool, tuple[tuple[float, ...], ...]]  # a copy's hide flags shown, and rounded vertices


def _set_frame(time_code: float) -> None:
    frame = int(time_code)
    bpy.data.scenes["Scene"].frame_set(frame, subframe=time_code - frame)


def _displayed(copies: Iterable[DisplayedCopy]) -> dict[str, _Shown]:
    """_SHOWN's copies as displayed, by source entity, their vertices rounded past keying's float error."""
    return {
        c.source_path: (
            c.visible_in_viewport,
            c.visible_in_render,
            tuple(tuple(round(x, 4) for x in v) for v in c.world_vertices),
        )
        for c in copies
        if c.source_path in _SHOWN
    }


def _clean_at(bindings: Bindings, stage: Usd.Stage, time_code: float) -> dict[str, _Shown]:
    return _displayed(clean_rebuild(bindings, stage, time_code=time_code).copies)


@pytest.mark.parametrize("grouping", range(3))
def test_each_cached_frame_shows_its_transforms_visibility_and_shear(
    bindings: Bindings, tmp_path: Path, grouping: int
) -> None:
    # CACHE-01, CACHE-09, XFORM-09 to XFORM-11 on F-TIME-VARIATIONS, cached by each grouping: at each cached time
    # code, and at a frame between two, Mover's and Skew's transforms, Blink's hide flags, and Shearing's shear, which
    # appears after 10, show what a clean synchronization at that time code, or the latest cached before, does; Still
    # is never keyed.
    with time_variations.time_variations(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage, scene.synchronized)
        for call in scene.cache_groupings[grouping]:
            assert handle.cache(call).state is not ResultState.FATAL_FAILURE, call
        assert time_variations.STILL not in _animated(handle)
        cached = sorted({scene.synchronized, *(t for call in scene.cache_groupings[grouping] for t in call)})
        frames = [*((t, t) for t in cached), (11.0, 10.0), (17.0, 15.0)]
        for frame, time_code in frames:
            expected = _clean_at(bindings, scene.stage, time_code)
            _set_frame(frame)
            assert _displayed(displayed_copies(handle.binding_id)) == expected, frame


def test_synchronizing_again_removes_shear_and_visibility_keys(bindings: Bindings, tmp_path: Path) -> None:
    # CHG-22 on F-TIME-VARIATIONS: cached, then synchronized at 0 again while showing 15, every copy shows 0's display,
    # no object holds an action, Mover, Blink, and Skew keep their objects, and Shearing, given a shear parent only
    # for its cached time codes, is rebuilt without one.
    with time_variations.time_variations(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage, scene.synchronized)
        [call] = scene.cache_groupings[0]
        assert handle.cache(call).state is not ResultState.FATAL_FAILURE
        before = {source: copy_object(entries) for source, entries in entries_by_source(handle.binding_id).items()}
        assert before[time_variations.SHEARING].parent is not None
        _set_frame(15.0)
        assert handle.synchronize(scene.synchronized).state is not ResultState.FATAL_FAILURE
        after = {source: copy_object(entries) for source, entries in entries_by_source(handle.binding_id).items()}
        assert not _animated(handle) and not bpy.data.actions
        assert all(after[s] == before[s] for s in (time_variations.MOVER, time_variations.BLINK, time_variations.SKEW))
        assert after[time_variations.SHEARING] != before[time_variations.SHEARING]
        assert after[time_variations.SHEARING].parent is None
        assert _displayed(displayed_copies(handle.binding_id)) == _clean_at(bindings, scene.stage, scene.synchronized)


def test_a_failing_call_takes_back_the_shear_parent_it_made(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CACHE-03 on F-TIME-VARIATIONS: a call caching 15, failing once it made Shearing's shear parent, unparents
    # Shearing and disposes of the parent, leaving the published generation and the file's datablocks as they were.
    new_shear_parent = time_code_keying._new_shear_parent  # noqa: SLF001 - the step's module function

    def failing(*args: Any) -> bpy.types.Object:
        new_shear_parent(*args)
        raise RuntimeError("injected keying failure")

    with time_variations.time_variations(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage, scene.synchronized)
        destination = bpy.data.collections["Shot"]
        published, before = published_generation(handle.binding_id, destination), datablocks()
        monkeypatch.setattr(time_code_keying, "_new_shear_parent", failing)
        assert handle.cache([15.0]).state is ResultState.FATAL_FAILURE
        assert published_generation(handle.binding_id, destination) == published
        assert datablocks() == before
        assert copy_object(entries_by_source(handle.binding_id)[time_variations.SHEARING]).parent is None
