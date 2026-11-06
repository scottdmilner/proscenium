"""Synchronizing through the API: acquisition and the attempt's time code (source-access.md#synchronization-api).

Through binding handles over a fresh process state per test, on bindings in the factory scene.
Their records, save/reopen, undo, and the attachment contract are in test_bindings.py.
"""

from __future__ import annotations

from pathlib import Path

import bpy
import pytest
from pxr import Usd, UsdUtils

from fixtures import source_access
from fixtures.scenes import Scene, copy_scene
from fixtures.source_access import DISK, read_values
from proscenium.api.bindings import (
    BindingHandle,
    BindingNotFoundError,
    Bindings,
    Result,
)
from proscenium.binding import persistence, runtime
from proscenium.binding.persistence import binding_state, configs, records
from proscenium.binding.results import DiagnosticCategory, DiagnosticCode, ResultState, Severity
from proscenium.binding.runtime import state
from proscenium.binding.source_access.identifiers import BindingId
from proscenium.binding.source_access.stages import PayloadPolicy
from support import undo
from support.usd import binding_on_file, open_fresh


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes[0]


def _root(tmp_path: Path) -> Path:
    return copy_scene(Scene.SOURCE_ACCESS, tmp_path) / "root.usda"


def _evaluation(bindings: Bindings, handle: BindingHandle) -> Usd.Stage:
    stages = bindings.stages.get(handle.binding_id)
    assert stages is not None and stages.evaluation_stage is not None
    return stages.evaluation_stage


def test_handles_are_equal_by_identifier(bindings: Bindings, tmp_path: Path) -> None:
    handle = binding_on_file(bindings, _scene(), _root(tmp_path))
    assert BindingHandle(handle.binding_id) == handle
    assert len({handle, BindingHandle(handle.binding_id)}) == 1
    assert binding_on_file(bindings, _scene(), _root(tmp_path / "other")) != handle


@pytest.mark.parametrize("time_code", [Usd.TimeCode.Default(), 0, 12, 7.25], ids=["default", "0", "12", "7.25"])
def test_the_time_code_is_the_attempts_not_a_setting(
    bindings: Bindings, tmp_path: Path, time_code: Usd.TimeCode | float
) -> None:
    # API-02: the default time code and numeric ones are accepted, and none becomes a setting.
    handle = binding_on_file(bindings, _scene(), _root(tmp_path), payload_policy=PayloadPolicy.LOAD_NONE)
    before = handle.requested_settings()
    assert handle.synchronize(time_code) == Result(time_codes=(Usd.TimeCode(time_code),))
    assert handle.requested_settings() == before
    stage = _evaluation(bindings, handle)
    assert read_values(stage) == DISK | {"payA": None, "payB": None}  # the attempt used the payload policy


def test_a_time_code_that_isnt_one_is_misuse(bindings: Bindings, tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        binding_on_file(bindings, _scene(), _root(tmp_path)).synchronize("frame 3")  # ty: ignore[invalid-argument-type]


def _recorded(handle: BindingHandle) -> tuple[float | None, float | None]:
    """The time codes the binding's last attempt and its generation record."""
    last = binding_state.read_last_attempt(_scene(), handle.binding_id)
    generation = binding_state.read_generation(bpy.data.collections["USD Display"])
    assert isinstance(last, records.Loaded) and isinstance(generation, records.Loaded)
    return last.record.time_code, generation.record.time_code


def _timing() -> tuple[object, ...]:
    """The scene's frame, frame rate, and playback range."""
    scene = _scene()
    frame = (scene.frame_current, scene.frame_subframe)
    return (*frame, scene.render.fps, scene.render.fps_base, scene.frame_start, scene.frame_end)


@pytest.mark.parametrize(
    ("time_code", "stored"), [(Usd.TimeCode.Default(), None), (0, 0.0), (7.25, 7.25)], ids=["default", "0", "7.25"]
)
def test_the_attempt_is_at_the_time_code_given(
    bindings: Bindings, tmp_path: Path, time_code: Usd.TimeCode | float, stored: float | None
) -> None:
    # BIND-05 on F-MULTI-BINDING "time-codes": the attempt, its last attempt, and its generation take it exactly.
    with source_access.multi_binding(tmp_path) as scene:
        handle = bindings.create_binding(_scene())
        assert handle.attach(scene.caller).state is ResultState.SUCCESS
        _scene().frame_set(3)  # not the current frame's
        result = handle.synchronize(time_code)
        assert (result.state, result.time_codes) == (ResultState.SUCCESS, (Usd.TimeCode(time_code),))
        assert _recorded(handle) == (stored, stored)


def test_without_a_time_code_the_attempt_is_at_the_current_frames(bindings: Bindings, tmp_path: Path) -> None:
    # BIND-05, XFORM-12 on F-MULTI-BINDING "time-codes": frame 7 at subframe 0.25 is time code 7.25, and the
    # scene's frame, frame rate, and playback range stay as they were.
    with source_access.multi_binding(tmp_path) as scene:
        handle = bindings.create_binding(_scene())
        assert handle.attach(scene.caller).state is ResultState.SUCCESS
        _scene().frame_set(7, subframe=0.25)
        before = _timing()
        result = handle.synchronize()
        assert (result.state, result.time_codes) == (ResultState.SUCCESS, (Usd.TimeCode(7.25),))
        assert _recorded(handle) == (7.25, 7.25)
        assert _timing() == before


def test_set_settings_records_without_synchronizing(bindings: Bindings, tmp_path: Path) -> None:
    # set_settings changes the requested settings only; the next synchronize uses them.
    handle = binding_on_file(bindings, _scene(), _root(tmp_path))
    handle.synchronize(3)
    stage = _evaluation(bindings, handle)
    assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE) == Result()
    assert handle.requested_settings().payload_policy is PayloadPolicy.LOAD_NONE
    assert read_values(stage) == DISK  # not applied yet
    handle.synchronize(3)
    assert read_values(stage) == DISK | {"payA": None, "payB": None}


def test_a_reload_keeps_the_synchronized_payload_policy(bindings: Bindings, tmp_path: Path) -> None:
    # Neither set_settings nor reload synchronizes, so evaluation keeps its synchronized payload policy.
    handle = binding_on_file(bindings, _scene(), _root(tmp_path))
    handle.synchronize(0)
    stage = _evaluation(bindings, handle)
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert handle.reload() == Result()
    assert read_values(stage) == DISK
    handle.synchronize(0)
    assert read_values(stage) == DISK | {"payA": None, "payB": None}


def test_a_reload_before_any_synchronization_opens_under_the_requested_policy(
    bindings: Bindings, tmp_path: Path
) -> None:
    handle = binding_on_file(bindings, _scene(), _root(tmp_path), payload_policy=PayloadPolicy.LOAD_NONE)
    assert handle.reload() == Result()
    stage = _evaluation(bindings, handle)
    assert read_values(stage) == DISK | {"payA": None, "payB": None}


def test_a_reload_after_attaching_opens_under_the_policy_requested_since(bindings: Bindings, tmp_path: Path) -> None:
    # Attaching makes the binding's source before any evaluation stage; the policy comes from the configuration.
    caller = open_fresh(_root(tmp_path))
    handle = bindings.create_binding(_scene())
    handle.attach(caller)
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert handle.reload() == Result()
    source = bindings.stages.get(handle.binding_id)
    assert source is not None
    evaluation = source.evaluation_stage
    assert evaluation is not None
    assert read_values(evaluation) == DISK | {"payA": None, "payB": None}


def test_set_settings_before_attachment_opens_nothing(bindings: Bindings) -> None:
    handle = bindings.create_binding(_scene())
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert handle.live_stage() is None
    assert bindings.stages.get(handle.binding_id) is None


def test_an_unchanged_configuration_is_not_written(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Setting nothing, or attaching the stage a binding already stored, leaves Blender data alone.
    caller = open_fresh(_root(tmp_path))
    handle = bindings.create_binding(_scene())
    handle.attach(caller)
    written: list[str] = []
    write = records.write

    def counted(id_: bpy.types.ID, key: str, *args: object) -> None:
        written.append(key)
        write(id_, key, *args)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr(records, "write", counted)
    assert handle.attach(caller) == Result()
    assert handle.set_settings() == Result()
    assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_ALL) == Result()  # the default
    assert written == []
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert written == [configs.config_key(handle.binding_id)]


def test_unavailable_source_is_a_result(bindings: Bindings) -> None:
    handle = bindings.create_binding(_scene())
    synchronized, reloaded = handle.synchronize(0), handle.reload()
    for result in (synchronized, reloaded):
        assert result.state == ResultState.FATAL_FAILURE
        assert [(d.code, d.category, d.severity) for d in result.diagnostics] == [
            (DiagnosticCode.NO_ATTACHED_STAGE, DiagnosticCategory.UNAVAILABLE_SOURCE, Severity.ERROR)
        ]
    # A failed synchronization still names the time code it attempted; a reload attempts none.
    assert (synchronized.time_codes, reloaded.time_codes) == ((Usd.TimeCode(0),), ())


def test_dirty_layers_are_reported_as_source_state(bindings: Bindings, tmp_path: Path) -> None:
    # The informational diagnostic names the dirty contributing layers and leaves the state success.
    with source_access.dirty_layer(tmp_path) as scene:
        result = binding_on_file(bindings, _scene(), scene.root).synchronize(0)
        assert result.state == ResultState.SUCCESS
        [diagnostic] = result.diagnostics
        assert (diagnostic.code, diagnostic.category, diagnostic.severity) == (
            DiagnosticCode.UNSAVED_LAYERS,
            DiagnosticCategory.SOURCE_STATE,
            Severity.INFO,
        )
        assert {Path(layer) for layer in diagnostic.layers} == set(scene.dirty_contributing.values())


def test_an_unchanged_refresh_reports_equal_diagnostics(bindings: Bindings, tmp_path: Path) -> None:
    # DIAG-07 on F-DIRTY-LAYER: nothing changes between the two, so they report equal diagnostics in the same order.
    with source_access.dirty_layer(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root)
        first, second = handle.synchronize(0), handle.synchronize(0)
        assert first.diagnostics
        assert second.diagnostics == first.diagnostics


def test_reload_doesnt_synchronize(bindings: Bindings, tmp_path: Path) -> None:
    # The reload rereads the layers; the requested settings are as they were, and the next synchronize shows it.
    with source_access.dirty_layer(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root)
        handle.synchronize(1)
        before = handle.requested_settings()
        assert handle.reload() == Result()
        assert handle.requested_settings() == before
        assert handle.synchronize(1) == Result(time_codes=(Usd.TimeCode(1),))  # nothing dirty left
        stage = handle.live_stage()
        assert stage is not None
        assert read_values(stage) == scene.disk_values


def test_reload_rejects_other_layers(bindings: Bindings, tmp_path: Path) -> None:
    handle = binding_on_file(bindings, _scene(), _root(tmp_path))
    with pytest.raises(ValueError, match="Not contributing layers"):
        handle.reload([str(tmp_path / "unknown.usda")])


def test_attaching_through_a_handle(bindings: Bindings, tmp_path: Path) -> None:
    root = _root(tmp_path)
    caller = open_fresh(root)
    handle = bindings.create_binding(_scene())
    assert handle.attach(caller) == Result()
    assert handle.synchronize(0) == Result(time_codes=(Usd.TimeCode(0),))
    assert handle.live_stage() == caller


def test_releasing_changes_only_its_binding(bindings: Bindings, tmp_path: Path) -> None:
    # SRC-02, API-12, SID-08: independent lifetimes even when stages are shared.
    with source_access.reattach(tmp_path) as scene:
        caller = scene.caller
        first, second = (bindings.create_binding(_scene()) for _ in range(2))
        for handle in (first, second):
            assert handle.attach(caller) == Result()
            assert handle.synchronize(0) == Result(time_codes=(Usd.TimeCode(0),))
        second_evaluation = _evaluation(bindings, second)
        before = records.stored(_scene(), configs.config_key(first.binding_id))
        assert first.release() is None
        assert first.release() is None
        assert records.stored(_scene(), configs.config_key(first.binding_id)) == before
        assert first.live_stage() is None
        assert [d.code for d in first.synchronize(0).diagnostics] == [DiagnosticCode.NO_ATTACHED_STAGE]
        assert second.live_stage() == caller
        assert _evaluation(bindings, second) == second_evaluation
        assert first.attach(caller) == Result()
        assert first.synchronize(0) == Result(time_codes=(Usd.TimeCode(0),))


def _counted_scans(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """One item for every time the bindings' state is rebuilt from the scenes' records from here on."""
    scans: list[int] = []
    read_configs = persistence.configs.read_configs

    def counted() -> object:
        scans.append(1)
        return read_configs()

    monkeypatch.setattr(persistence.configs, "read_configs", counted)
    return scans


def test_an_undo_with_no_sources_rebuilds_nothing_in_its_handler(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bindings exist, but none has been synchronized this session: nothing to prune.
    undo.require_global_undo()
    handle = bindings.create_binding(_scene())
    undo.push("base")
    bpy.data.objects.new("Unrelated", None)
    undo.push("edit")
    scans = _counted_scans(monkeypatch)
    undo.undo()
    assert scans == []
    handle.synchronize(0)  # unavailable; the next call rebuilds the state once
    assert scans == [1]
    undo.redo()  # now with a source: pruned at once
    assert scans == [1, 1]


def test_pruning_compares_the_scenes_once(bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handles = [binding_on_file(bindings, _scene(), _root(tmp_path / str(i)), name=f"B{i}") for i in range(3)]
    for handle in handles:
        handle.synchronize(0)
    current, calls = state.current_state, []  # the cost under test is one comparison of the scenes

    def counted() -> object:
        calls.append(1)
        return current()

    monkeypatch.setattr(state, "current_state", counted)
    bindings.prune_stages()
    assert len(calls) == 1
    assert all(bindings.stages.get(handle.binding_id) is not None for handle in handles)


def test_undoing_an_attached_bindings_creation_keeps_its_attachment(bindings: Bindings, tmp_path: Path) -> None:
    # UNDO-06: undo neither restores nor removes attachments. The binding's evaluation stage goes; the
    # attachment stays for redo, and handle.release() still releases it while the binding doesn't exist.
    undo.require_global_undo()
    caller = open_fresh(_root(tmp_path))
    undo.push("base")
    handle = bindings.create_binding(_scene())
    handle.attach(caller)
    assert handle.synchronize(0) == Result(time_codes=(Usd.TimeCode(0),))
    source = bindings.stages.get(handle.binding_id)
    assert source is not None
    undo.push("create")
    undo.undo()
    assert source.evaluation_stage is None
    assert source.live_stage == caller
    undo.redo()
    assert handle.live_stage() == caller
    assert handle.synchronize(0) == Result(time_codes=(Usd.TimeCode(0),))
    undo.undo()
    assert handle.release() is None  # the record no longer exists
    assert source.live_stage is None
    undo.redo()
    assert handle.live_stage() is None
    assert handle.synchronize(0).state is ResultState.FATAL_FAILURE


def test_a_removed_scenes_binding_keeps_only_its_attachment(bindings: Bindings, tmp_path: Path) -> None:
    scene = _scene()
    other = bpy.data.scenes.new("Other")
    removed = binding_on_file(bindings, other, _root(tmp_path))
    kept = binding_on_file(bindings, scene, _root(tmp_path))
    for handle in (removed, kept):
        assert handle.synchronize(0) == Result(time_codes=(Usd.TimeCode(0),))
    source = bindings.stages.get(removed.binding_id)
    assert source is not None
    caller = source.live_stage
    bpy.data.scenes.remove(other)
    assert kept.synchronize(0) == Result(time_codes=(Usd.TimeCode(0),))
    assert source.evaluation_stage is None
    assert source.live_stage == caller
    assert bindings.stages.get(kept.binding_id) is not None
    assert removed.release() is None
    assert (source.live_stage, source.evaluation_stage) == (None, None)
    assert kept.live_stage() is not None


@pytest.mark.parametrize("unusable", ["unreadable", "disabled"])
def test_an_unusable_binding_keeps_its_stages_but_has_no_live_stage(
    bindings: Bindings, tmp_path: Path, unusable: str
) -> None:
    handle = binding_on_file(bindings, _scene(), _root(tmp_path))
    assert handle.synchronize(0) == Result(time_codes=(Usd.TimeCode(0),))
    stages = bindings.stages.get(handle.binding_id)
    assert stages is not None
    caller, evaluation = stages.live_stage, stages.evaluation_stage
    if unusable == "unreadable":
        _scene()[records.NAMESPACE][configs.config_key(handle.binding_id)][records.VERSION_KEY] = 99
    else:
        [text] = configs.index_texts()
        text.copy()  # two indexes naming the identity leave no canonical candidate
    runtime.state.invalidate()
    assert handle.synchronize(0).state == ResultState.FATAL_FAILURE
    assert handle.live_stage() is None
    assert bindings.stages.get(handle.binding_id) is stages
    assert stages.live_stage == caller
    assert stages.evaluation_stage == evaluation


def test_live_stage_through_the_handle(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-07, ICON-34: callers may attach a cached stage; evaluation never substitutes it for the live stage.
    with source_access.cached_stage(tmp_path) as scene:
        handle = bindings.create_binding(_scene())
        assert handle.live_stage() is None
        handle.attach(scene.ambient)
        assert handle.live_stage() == scene.ambient  # before any synchronization
        assert UsdUtils.StageCache.Get().Contains(scene.ambient)
        handle.synchronize(0)
        evaluation = _evaluation(bindings, handle)
        assert evaluation != scene.ambient
        assert not UsdUtils.StageCache.Get().Contains(evaluation)
        assert handle.live_stage() == scene.ambient


def test_a_handle_to_no_binding_raises(bindings: Bindings) -> None:
    handle = BindingHandle(BindingId("not-a-binding"))
    calls = [
        lambda: handle.attach(Usd.Stage.CreateInMemory()),
        lambda: handle.synchronize(0),
        lambda: handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE),
        handle.reload,
        handle.requested_settings,
        handle.live_stage,
    ]
    for call in calls:
        with pytest.raises(BindingNotFoundError):
            call()

    assert handle.release() is None
