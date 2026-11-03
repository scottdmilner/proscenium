"""The synchronization API's entry point, acquisition only (source-access.md#synchronization-api).

Through binding handles over a fresh process state per test, on bindings in the factory scene.
Their records, save/reopen, undo, and the key contract are in test_bindings.py.
"""

from __future__ import annotations

from pathlib import Path

import bpy
import pytest
from pxr import Usd, UsdUtils

from fixtures import source_access
from fixtures.scenes import Scene, copy_scene
from fixtures.source_access import DISK, read_values
from proscenium import runtime
from proscenium.api.bindings import (
    BindingHandle,
    BindingNotFoundError,
    Bindings,
    DiagnosticCategory,
    Result,
    ResultState,
    Severity,
)
from proscenium.core.binding_ids import BindingId
from proscenium.core.source_access import PayloadPolicy
from proscenium.persistence import binding_records, records
from proscenium.runtime import state
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
    assert handle.synchronize(time_code) == Result(ResultState.SUCCESS)
    assert handle.requested_settings() == before
    stage = _evaluation(bindings, handle)
    assert read_values(stage) == DISK | {"payA": None, "payB": None}  # the attempt used the payload policy


def test_a_time_code_that_isnt_one_is_misuse(bindings: Bindings, tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        binding_on_file(bindings, _scene(), _root(tmp_path)).synchronize("frame 3")  # ty: ignore[invalid-argument-type]


def test_set_settings_records_without_synchronizing(bindings: Bindings, tmp_path: Path) -> None:
    # set_settings changes the requested settings only; the next synchronize uses them.
    handle = binding_on_file(bindings, _scene(), _root(tmp_path))
    handle.synchronize(3)
    stage = _evaluation(bindings, handle)
    assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE) == Result(ResultState.SUCCESS)
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
    assert handle.reload() == Result(ResultState.SUCCESS)
    assert read_values(stage) == DISK
    handle.synchronize(0)
    assert read_values(stage) == DISK | {"payA": None, "payB": None}


def test_a_reload_before_any_synchronization_opens_under_the_requested_policy(
    bindings: Bindings, tmp_path: Path
) -> None:
    handle = binding_on_file(bindings, _scene(), _root(tmp_path), payload_policy=PayloadPolicy.LOAD_NONE)
    assert handle.reload() == Result(ResultState.SUCCESS)
    stage = _evaluation(bindings, handle)
    assert read_values(stage) == DISK | {"payA": None, "payB": None}


def test_a_reload_after_attaching_opens_under_the_policy_requested_since(bindings: Bindings, tmp_path: Path) -> None:
    # Attaching makes the binding's source before any evaluation stage; the policy comes from the configuration.
    caller = open_fresh(_root(tmp_path))
    handle = bindings.create_binding(_scene(), "shot")
    bindings.attach("shot", caller)
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert handle.reload() == Result(ResultState.SUCCESS)
    source = bindings.stages.get(handle.binding_id)
    assert source is not None
    evaluation = source.evaluation_stage
    assert evaluation is not None
    assert read_values(evaluation) == DISK | {"payA": None, "payB": None}


def test_set_settings_before_attachment_opens_nothing(bindings: Bindings) -> None:
    handle = bindings.create_binding(_scene(), "shot")
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert handle.live_stage() is None
    assert bindings.stages.get(handle.binding_id) is None


def test_an_unchanged_configuration_is_not_written(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Setting nothing, or attaching the stage a binding already stored, leaves Blender data alone.
    caller = open_fresh(_root(tmp_path))
    handle = bindings.create_binding(_scene(), "shot")
    bindings.attach("shot", caller)
    written: list[str] = []
    write = records.write

    def counted(id_: bpy.types.ID, key: str, *args: object) -> None:
        written.append(key)
        write(id_, key, *args)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr(records, "write", counted)
    assert bindings.attach("shot", caller).attached == (handle.binding_id,)
    assert handle.set_settings() == Result(ResultState.SUCCESS)
    assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_ALL) == Result(ResultState.SUCCESS)  # the default
    assert written == []
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert written == [binding_records.config_key(handle.binding_id)]


def test_unavailable_source_is_a_result(bindings: Bindings) -> None:
    handle = bindings.create_binding(_scene(), "shot")
    for result in (handle.synchronize(0), handle.reload()):
        assert result.state == ResultState.FATAL_FAILURE
        assert [(d.category, d.severity) for d in result.diagnostics] == [
            (DiagnosticCategory.UNAVAILABLE_SOURCE, Severity.ERROR)
        ]


def test_dirty_layers_are_reported_as_source_state(bindings: Bindings, tmp_path: Path) -> None:
    # The informational diagnostic names the dirty contributing layers and leaves the state success.
    with source_access.dirty_layer(tmp_path) as scene:
        result = binding_on_file(bindings, _scene(), scene.root).synchronize(0)
        assert result.state == ResultState.SUCCESS
        [diagnostic] = result.diagnostics
        assert (diagnostic.category, diagnostic.severity) == (DiagnosticCategory.SOURCE_STATE, Severity.INFO)
        assert {Path(layer) for layer in diagnostic.layers} == set(scene.dirty_contributing.values())


def test_reload_doesnt_synchronize(bindings: Bindings, tmp_path: Path) -> None:
    # The reload rereads the layers; the requested settings are as they were, and the next synchronize shows it.
    with source_access.dirty_layer(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root)
        handle.synchronize(1)
        before = handle.requested_settings()
        assert handle.reload() == Result(ResultState.SUCCESS)
        assert handle.requested_settings() == before
        assert handle.synchronize(1) == Result(ResultState.SUCCESS)  # nothing dirty left
        stage = handle.live_stage()
        assert stage is not None
        assert read_values(stage) == scene.disk_values


def test_reload_rejects_other_layers(bindings: Bindings, tmp_path: Path) -> None:
    handle = binding_on_file(bindings, _scene(), _root(tmp_path))
    with pytest.raises(ValueError, match="Not contributing layers"):
        handle.reload([str(tmp_path / "unknown.usda")])


def test_attaching_under_a_key(bindings: Bindings, tmp_path: Path) -> None:
    root = _root(tmp_path)
    caller = open_fresh(root)
    handle = bindings.create_binding(_scene(), "shot")
    assert bindings.attach("shot", caller).attached == (handle.binding_id,)
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    assert handle.live_stage() == caller


def test_releasing_under_a_key(bindings: Bindings, tmp_path: Path) -> None:
    # SRC-02: release(key) leaves every binding with the key unattached; others keep their stage.
    caller = open_fresh(_root(tmp_path))
    first, second = (bindings.create_binding(_scene(), "shot") for _ in range(2))
    other = bindings.create_binding(_scene(), "other")
    bindings.attach("shot", caller)
    bindings.attach("other", caller)
    for handle in (first, second, other):
        assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    assert bindings.release("shot") == (first.binding_id, second.binding_id)
    for handle in (first, second):
        assert handle.live_stage() is None
        assert [d.category for d in handle.synchronize(0).diagnostics] == [DiagnosticCategory.UNAVAILABLE_SOURCE]
    assert other.live_stage() == caller
    assert bindings.attach("shot", caller).attached == (first.binding_id, second.binding_id)  # attachable again
    assert first.synchronize(0) == Result(ResultState.SUCCESS)


def _counted_scans(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """One item for every time the bindings' state is rebuilt from the scenes' records from here on."""
    scans: list[int] = []
    read_configs = binding_records.read_configs

    def counted() -> object:
        scans.append(1)
        return read_configs()

    monkeypatch.setattr(binding_records, "read_configs", counted)
    return scans


def test_an_undo_with_no_sources_rebuilds_nothing_in_its_handler(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bindings exist, but none has been synchronized this session: nothing to prune.
    undo.require_global_undo()
    handle = bindings.create_binding(_scene(), "shot")
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
    # attachment stays for redo, and release(key) still releases it while the binding doesn't exist.
    undo.require_global_undo()
    caller = open_fresh(_root(tmp_path))
    undo.push("base")
    handle = bindings.create_binding(_scene(), "shot")
    bindings.attach("shot", caller)
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    source = bindings.stages.get(handle.binding_id)
    assert source is not None
    undo.push("create")
    undo.undo()
    assert source.evaluation_stage is None
    assert source.live_stage == caller
    undo.redo()
    assert handle.live_stage() == caller
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    undo.undo()
    assert bindings.release("shot") == ()  # no binding with the key exists
    assert source.live_stage is None


def test_a_removed_scenes_binding_keeps_only_its_attachment(bindings: Bindings, tmp_path: Path) -> None:
    scene = _scene()
    other = bpy.data.scenes.new("Other")
    removed = binding_on_file(bindings, other, _root(tmp_path))
    kept = binding_on_file(bindings, scene, _root(tmp_path))
    for handle in (removed, kept):
        assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    source = bindings.stages.get(removed.binding_id)
    assert source is not None
    caller = source.live_stage
    bpy.data.scenes.remove(other)
    assert kept.synchronize(0) == Result(ResultState.SUCCESS)
    assert source.evaluation_stage is None
    assert source.live_stage == caller
    assert bindings.stages.get(kept.binding_id) is not None


@pytest.mark.parametrize("unusable", ["unreadable", "disabled"])
def test_an_unusable_binding_keeps_its_stages_but_has_no_live_stage(
    bindings: Bindings, tmp_path: Path, unusable: str
) -> None:
    handle = binding_on_file(bindings, _scene(), _root(tmp_path))
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    stages = bindings.stages.get(handle.binding_id)
    assert stages is not None
    caller, evaluation = stages.live_stage, stages.evaluation_stage
    if unusable == "unreadable":
        _scene()[records.NAMESPACE][binding_records.config_key(handle.binding_id)][records.VERSION_KEY] = 99
    else:
        [text] = binding_records.index_texts()
        text.copy()  # two indexes naming the identity leave no canonical candidate
    runtime.invalidate()
    assert handle.synchronize(0).state == ResultState.FATAL_FAILURE
    assert handle.live_stage() is None
    assert bindings.stages.get(handle.binding_id) is stages
    assert stages.live_stage == caller
    assert stages.evaluation_stage == evaluation


def test_live_stage_through_the_handle(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-07, ICON-34: callers may attach a cached stage; evaluation never substitutes it for the live stage.
    with source_access.cached_stage(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), "shot")
        assert handle.live_stage() is None
        bindings.attach("shot", scene.ambient)
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
        lambda: handle.synchronize(0),
        lambda: handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE),
        handle.reload,
        handle.requested_settings,
        handle.live_stage,
    ]
    for call in calls:
        with pytest.raises(BindingNotFoundError):
            call()
