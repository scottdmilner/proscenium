"""What a cache call keys: the copies that vary, found by comparing plans (M7 plan, D1).

DECISIONS.md "What a cache call keys". A cache call compares the plan at each time code it caches with the generation's
own, held since it was published, and keys the copies a time code moves, at every time code the generation holds: one
keyed for the first time is keyed with the value it showed at the generation's own time code and at those cached before,
where it didn't differ. A copy equal everywhere has no keys. Without the generation's plan held, every copy is keyed.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import bpy
import pytest
from pxr import Gf, Usd

from fixtures import edit_sequence, incremental, time_variations
from proscenium_sync.persistence import binding_state, id_property_records
from proscenium_sync.persistence.manifests import RepresentationRole
from proscenium_sync.results import DiagnosticCode, ResultState
from proscenium_sync.runtime import ownership, pending_cleanup
from proscenium_sync.synchronization import attribute_samples, time_code_keying
from support.blend import save_and_reopen
from support.clean_rebuild import clean_rebuild
from support.displayed_copies import displayed_copies
from support.refresh_checks import copy_object, entries_by_source
from support.time_codes import sampled

from .published_state import datablocks, published_generation

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from proscenium_sync.bindings import BindingHandle, Bindings
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


type _Shown = tuple[bool, bool, tuple[tuple[float, ...], ...]]  # a copy's hide flags shown, and world vertices


def _set_frame(time_code: float) -> None:
    """Show time_code's frame, its fraction the subframe (XFORM-11)."""
    frame = math.floor(time_code)
    bpy.data.scenes["Scene"].frame_set(frame, subframe=time_code - frame)


def _displayed(copies: Iterable[DisplayedCopy]) -> dict[str, _Shown]:
    """Each copy shown in a destination, by source entity, its flags and world vertices.

    One hidden in both shows nothing, as a copy that isn't drawn doesn't: a copy absent at a time code, or the other
    form's object of a placeholder that is a box at some and a marker at others.
    """
    found: dict[str, _Shown] = {}
    for c in copies:
        if c.visible_in_viewport or c.visible_in_render:
            assert c.source_path not in found, c.source_path  # one object of a copy shows
            vertices = tuple(tuple(v) for v in c.world_vertices)
            found[c.source_path] = (c.visible_in_viewport, c.visible_in_render, vertices)
    return found


def _assert_shown(copies: Iterable[DisplayedCopy], expected: dict[str, _Shown], label: object) -> None:
    """Assert copies show what expected does, their vertices within keying's float error."""
    shown = _displayed(copies)
    assert shown.keys() == expected.keys(), label
    for source, (viewport, render, vertices) in shown.items():
        assert (viewport, render) == expected[source][:2], (label, source)
        flat = [x for v in vertices for x in v]
        assert flat == pytest.approx([x for v in expected[source][2] for x in v], abs=1e-5), (label, source)


def _clean_at(bindings: Bindings, stage: Usd.Stage, time_code: float) -> dict[str, _Shown]:
    return _displayed(clean_rebuild(bindings, stage, time_code=time_code).copies)


@pytest.mark.parametrize("grouping", range(3))
def test_each_cached_frame_shows_its_transforms_visibility_and_shear(
    bindings: Bindings, tmp_path: Path, grouping: int
) -> None:
    # CACHE-01, CACHE-09, XFORM-09 to XFORM-11 on F-TIME-VARIATIONS, cached by each grouping: at each cached time
    # code, and at a frame between two, Mover's and Skew's transforms, Blink's hide flags, Shearing's shear, which
    # appears after 10, Grows' bounds, through its frames modifier, Flicker, a marker given a box for [10, 20), and
    # Scatter's points, whose third appears and whose second takes Stone for [10, 20), built by the call, show what a
    # clean synchronization at that time code, or the latest cached before, does; Still is never keyed.
    with time_variations.time_variations(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage, scene.synchronized)
        for call in scene.cache_groupings[grouping]:
            assert handle.cache(call).state is not ResultState.FATAL_FAILURE, call
        assert time_variations.STILL not in _animated(handle)
        cached = sorted({scene.synchronized, *(t for call in scene.cache_groupings[grouping] for t in call)})
        frames = [*((t, t) for t in cached), (11.0, 10.0), (17.0, 15.0), (-3.0, 0.0)]  # before 0, 0's (XFORM-13)
        for frame, time_code in frames:
            expected = _clean_at(bindings, scene.stage, time_code)
            _set_frame(frame)
            _assert_shown(displayed_copies(handle.binding_id, evaluated=True), expected, frame)


def test_synchronizing_again_removes_what_a_cache_call_added(bindings: Bindings, tmp_path: Path) -> None:
    # CHG-22 on F-TIME-VARIATIONS: cached, then synchronized at 0 again while showing 15, every copy shows 0's display,
    # no object holds an action, Mover, Blink, and Skew keep their objects, Shearing, given a shear parent only for its
    # cached time codes, is rebuilt without one, Grows, whose bounds were sampled, is rebuilt, the frames group gone
    # with its old object, and Flicker, given a box, is rebuilt as its marker alone.
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
        assert after[time_variations.GROWS] != before[time_variations.GROWS] and not bpy.data.node_groups
        sources = set(entries_by_source(handle.binding_id))
        assert sources == {source for source, _ in scene.copies(scene.synchronized)}  # the built points' gone
        flicker = entries_by_source(handle.binding_id)[time_variations.FLICKER].values()
        assert after[time_variations.FLICKER] != before[time_variations.FLICKER]
        assert [e.role for e in flicker] == [RepresentationRole.OBJECT]  # its marker alone
        shown = displayed_copies(handle.binding_id, evaluated=True)
        _assert_shown(shown, _clean_at(bindings, scene.stage, scene.synchronized), scene.synchronized)


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


def test_a_failing_call_takes_back_its_samples(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CACHE-03 on F-TIME-VARIATIONS: a first call failing once it sampled Grows' bounds removes the sample and the
    # frames modifier and disposes of the frames group, leaving the published generation and the file's datablocks as
    # they were.
    add_sample = attribute_samples.add_sample

    def failing(*args: Any) -> str:
        add_sample(*args)
        raise RuntimeError("injected keying failure")

    with time_variations.time_variations(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage, scene.synchronized)
        destination = bpy.data.collections["Shot"]
        published, before = published_generation(handle.binding_id, destination), datablocks()
        monkeypatch.setattr(attribute_samples, "add_sample", failing)
        assert handle.cache([5.0]).state is ResultState.FATAL_FAILURE
        assert published_generation(handle.binding_id, destination) == published
        assert datablocks() == before
        grows = copy_object(entries_by_source(handle.binding_id)[time_variations.GROWS])
        assert not grows.modifiers
        assert isinstance(grows.data, bpy.types.Mesh)
        assert not any("@" in attribute.name for attribute in grows.data.attributes)


def test_a_failing_frames_group_leaves_no_untracked_node_group(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # TXN-08/CACHE-03: the group is tracked when allocated, so one whose population fails is disposed of.
    with time_variations.time_variations(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage, scene.synchronized)
        destination = bpy.data.collections["Shot"]
        published, before = published_generation(handle.binding_id, destination), datablocks()
        records = _records(destination)
        with monkeypatch.context() as patch:
            patch.setattr(attribute_samples, "_SAMPLE_SOCKET", "not the actual socket")
            result = handle.cache([5.0])
        assert result.state is ResultState.FATAL_FAILURE
        assert any(
            d.code is DiagnosticCode.PREPARATION_FAILED and "Expected input Sample" in d.message
            for d in result.diagnostics
        )
        assert published_generation(handle.binding_id, destination) == published
        assert _records(destination) == records
        assert datablocks() == before
        assert pending_cleanup.nothing_pending(handle.binding_id)
        assert handle.cache([5.0]).state is not ResultState.FATAL_FAILURE


def test_a_failing_call_takes_back_the_box_it_made(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CACHE-03 on F-TIME-VARIATIONS: a call caching 15, failing once it made Flicker's box, unlinks and disposes of it
    # and its mesh, leaving the published generation and the file's datablocks as they were.
    new_other_form = time_code_keying._new_other_form  # noqa: SLF001 - the step's module function

    def failing(*args: Any) -> bpy.types.Object:
        new_other_form(*args)
        raise RuntimeError("injected keying failure")

    with time_variations.time_variations(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage, scene.synchronized)
        destination = bpy.data.collections["Shot"]
        published, before = published_generation(handle.binding_id, destination), datablocks()
        monkeypatch.setattr(time_code_keying, "_new_other_form", failing)
        assert handle.cache([15.0]).state is ResultState.FATAL_FAILURE
        assert published_generation(handle.binding_id, destination) == published
        assert datablocks() == before


def test_a_failing_call_takes_back_the_copies_it_built(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CACHE-03 on F-TIME-VARIATIONS: a call caching 15, failing once it built Scatter's points that appear there,
    # unlinks and disposes of them, leaving the published generation and the file's datablocks as they were.
    build_copy = time_code_keying._CallKeying._build_copy  # noqa: SLF001 - the step's method
    built: list[None] = []

    def failing(call: Any, *args: Any) -> None:
        build_copy(call, *args)
        built.append(None)
        if len(built) == 2:  # both of 15's new copies
            raise RuntimeError("injected keying failure")

    with time_variations.time_variations(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage, scene.synchronized)
        destination = bpy.data.collections["Shot"]
        published, before = published_generation(handle.binding_id, destination), datablocks()
        monkeypatch.setattr(time_code_keying._CallKeying, "_build_copy", failing)  # noqa: SLF001
        assert handle.cache([15.0]).state is ResultState.FATAL_FAILURE
        assert published_generation(handle.binding_id, destination) == published
        assert datablocks() == before


@pytest.mark.parametrize("order", ["increasing", "decreasing"])
def test_each_sampled_time_code_cached_one_at_a_time(bindings: Bindings, tmp_path: Path, order: str) -> None:
    # CACHE-01, CACHE-10 on F-TIME-VARIATIONS: synchronized at a sampled time code between its samples, then each other
    # sampled time code cached by a call of its own, in increasing and in decreasing order, every call succeeds and
    # each one's frame shows what a clean synchronization there does, those before the range and between frames
    # included.
    with time_variations.time_variations(tmp_path) as scene:
        sampled_codes = sampled("F-TIME-VARIATIONS", scene.variation)
        synchronized = sampled_codes.interior
        handle = _synchronized(bindings, scene.stage, synchronized)
        cached = sorted(t for t in sampled_codes.time_codes if t is not None and t != synchronized)
        for time_code in cached if order == "increasing" else reversed(cached):
            assert handle.cache([time_code]).state is not ResultState.FATAL_FAILURE, time_code
        for time_code in [synchronized, *cached]:
            expected = _clean_at(bindings, scene.stage, time_code)
            _set_frame(time_code)
            _assert_shown(displayed_copies(handle.binding_id, evaluated=True), expected, time_code)


def _records(destination: bpy.types.Collection) -> tuple[object, object]:
    """The destination's generation record, its cached time codes included, and its last attempt, as stored."""
    return (
        id_property_records.stored(destination, binding_state.GENERATION_KEY),
        id_property_records.stored(destination, binding_state.ATTEMPT_KEY),
    )


def test_the_display_never_synchronizes_or_caches_on_its_own(bindings: Bindings, tmp_path: Path) -> None:
    # CACHE-08 on F-TIME-VARIATIONS: synchronized and cached, changing the frame, editing the live stage, and saving
    # and reopening leave the generation record, its cached time codes, and the last attempt as they were.
    with time_variations.time_variations(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage, scene.synchronized)
        [call] = scene.cache_groupings[0]
        assert handle.cache(call).state is not ResultState.FATAL_FAILURE
        records = _records(bpy.data.collections["Shot"])
        _set_frame(15.0)
        assert _records(bpy.data.collections["Shot"]) == records
        scene.stage.GetAttributeAtPath(f"{time_variations.STILL}.xformOp:translate").Set(Gf.Vec3d(1, 2, 3))
        assert _records(bpy.data.collections["Shot"]) == records
        save_and_reopen(tmp_path / "cached.blend")
        assert _records(bpy.data.collections["Shot"]) == records


def test_what_a_call_makes_is_managed(bindings: Bindings, tmp_path: Path) -> None:
    # XFORM-09 on F-TIME-VARIATIONS: every action, node group, and sampled mesh a cache call makes or samples is named
    # in the binding's manifest, and synchronizing again retires them, leaving none.
    with time_variations.time_variations(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage, scene.synchronized)
        [call] = scene.cache_groupings[0]
        assert handle.cache(call).state is not ResultState.FATAL_FAILURE
        named = {e.datablock for entries in entries_by_source(handle.binding_id).values() for e in entries.values()}
        manifest = ownership.manifest(handle.binding_id)
        assert isinstance(manifest, id_property_records.LoadedRecord)
        named |= {e.datablock for e in manifest.record.entries.values()}
        sampled_meshes = [m for m in bpy.data.meshes if any("@" in a.name for a in m.attributes)]
        assert bpy.data.actions and bpy.data.node_groups and sampled_meshes
        assert {*bpy.data.actions, *bpy.data.node_groups, *sampled_meshes} <= named
        assert handle.synchronize(scene.synchronized).state is not ResultState.FATAL_FAILURE
        assert not bpy.data.actions and not bpy.data.node_groups
        assert not any("@" in a.name for m in bpy.data.meshes for a in m.attributes)


def test_synchronizing_and_caching_leave_the_scenes_time_as_it_was(bindings: Bindings, tmp_path: Path) -> None:
    # XFORM-10 on F-TIME-VARIATIONS: the target scene's frame rate, frame range, and current frame are as before.
    target = bpy.data.scenes["Scene"]

    def scene_time() -> tuple[object, ...]:
        render = target.render
        return render.fps, render.fps_base, target.frame_start, target.frame_end, target.frame_current

    with time_variations.time_variations(tmp_path) as scene:
        before = scene_time()
        handle = _synchronized(bindings, scene.stage, scene.synchronized)
        for call in scene.cache_groupings[2]:
            assert handle.cache(call).state is not ResultState.FATAL_FAILURE
        assert scene_time() == before


@pytest.mark.parametrize("fps", [24, 30])
def test_a_subframe_shows_its_time_code(bindings: Bindings, tmp_path: Path, fps: int) -> None:
    # XFORM-11 on F-TIME-VARIATIONS at 24 and 30 frames per second: the time code cached at 12.5 shows at frame 12,
    # subframe 0.5, what a synchronization at 12.5 does, and a synchronization without a time code there is at 12.5.
    target = bpy.data.scenes["Scene"]
    target.render.fps = fps
    with time_variations.time_variations(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage, scene.synchronized)
        assert handle.cache([12.5]).state is not ResultState.FATAL_FAILURE
        expected = _clean_at(bindings, scene.stage, 12.5)
        target.frame_set(12, subframe=0.5)
        _assert_shown(displayed_copies(handle.binding_id, evaluated=True), expected, 12.5)
        result = handle.synchronize()
        assert result.attempted_time_codes == (Usd.TimeCode(12.5),)
        target.frame_set(12, subframe=0.5)
        _assert_shown(displayed_copies(handle.binding_id, evaluated=True), expected, 12.5)
