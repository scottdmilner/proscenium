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
from proscenium.api.synchronization import (
    BindingHandle,
    BindingNotFoundError,
    Category,
    Result,
    ResultState,
    Severity,
    Synchronization,
)
from proscenium.core.source_access import PayloadPolicy
from proscenium.persistence import bindings, records
from proscenium.runtime import state
from support import undo
from support.usd import open_fresh


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes[0]


def _root(tmp_path: Path) -> Path:
    return copy_scene(Scene.SOURCE_ACCESS, tmp_path) / "root.usda"


def test_handles_are_equal_by_identifier(sync: Synchronization, tmp_path: Path) -> None:
    handle = sync.create_file_binding(_scene(), _root(tmp_path))
    assert BindingHandle(handle.binding_id) == handle
    assert len({handle, BindingHandle(handle.binding_id)}) == 1
    assert sync.create_file_binding(_scene(), _root(tmp_path / "other")) != handle


@pytest.mark.parametrize("time_code", [Usd.TimeCode.Default(), 0, 12, 7.25], ids=["default", "0", "12", "7.25"])
def test_the_time_code_is_the_attempts_not_a_setting(
    sync: Synchronization, tmp_path: Path, time_code: Usd.TimeCode | float
) -> None:
    # API-02: the default time code and numeric ones are accepted, and none becomes a setting.
    handle = sync.create_file_binding(_scene(), _root(tmp_path), payload_policy=PayloadPolicy.LOAD_NONE)
    before = handle.requested_settings()
    assert handle.synchronize(time_code) == Result(ResultState.SUCCESS)
    assert handle.requested_settings() == before
    stage = handle.live_stage()
    assert stage is not None
    assert read_values(stage) == DISK | {"payA": None, "payB": None}  # the attempt used the payload policy


def test_a_time_code_that_isnt_one_is_misuse(sync: Synchronization, tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        sync.create_file_binding(_scene(), _root(tmp_path)).synchronize("frame 3")  # ty: ignore[invalid-argument-type]


def test_set_settings_records_without_synchronizing(sync: Synchronization, tmp_path: Path) -> None:
    # set_settings changes the requested settings only; the next synchronize uses them.
    handle = sync.create_file_binding(_scene(), _root(tmp_path))
    handle.synchronize(3)
    stage = handle.live_stage()
    assert stage is not None
    assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE) == Result(ResultState.SUCCESS)
    assert handle.requested_settings().payload_policy is PayloadPolicy.LOAD_NONE
    assert read_values(stage) == DISK  # not applied yet
    handle.synchronize(3)
    assert read_values(stage) == DISK | {"payA": None, "payB": None}


def test_a_reload_keeps_the_synchronized_payload_policy(sync: Synchronization, tmp_path: Path) -> None:
    # Neither set_settings nor reload synchronizes, so the live stage keeps the policy it was synchronized with.
    handle = sync.create_file_binding(_scene(), _root(tmp_path))
    handle.synchronize(0)
    stage = handle.live_stage()
    assert stage is not None
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert handle.reload() == Result(ResultState.SUCCESS)
    assert read_values(stage) == DISK
    handle.synchronize(0)
    assert read_values(stage) == DISK | {"payA": None, "payB": None}


def test_a_reload_before_any_synchronization_opens_under_the_requested_policy(
    sync: Synchronization, tmp_path: Path
) -> None:
    handle = sync.create_file_binding(_scene(), _root(tmp_path), payload_policy=PayloadPolicy.LOAD_NONE)
    assert handle.reload() == Result(ResultState.SUCCESS)
    stage = handle.live_stage()
    assert stage is not None
    assert read_values(stage) == DISK | {"payA": None, "payB": None}


def test_a_reload_after_attaching_opens_under_the_policy_requested_since(sync: Synchronization, tmp_path: Path) -> None:
    # Attaching makes the binding's source before any evaluation stage; the policy comes from the configuration.
    caller = open_fresh(_root(tmp_path))
    handle = sync.create_attached_binding(_scene(), "shot")
    sync.attach("shot", caller)
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert handle.reload() == Result(ResultState.SUCCESS)
    source = sync.sources.get(handle.binding_id)
    assert source is not None
    evaluation = source.evaluation_stage
    assert evaluation is not None
    assert read_values(evaluation) == DISK | {"payA": None, "payB": None}


def test_set_settings_before_the_first_synchronization_opens_nothing(sync: Synchronization, tmp_path: Path) -> None:
    handle = sync.create_file_binding(_scene(), _root(tmp_path))
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert handle.live_stage() is None


def test_an_unchanged_configuration_is_not_written(
    sync: Synchronization, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Setting nothing, or attaching the stage a binding already stored, leaves Blender data alone.
    caller = open_fresh(_root(tmp_path))
    handle = sync.create_attached_binding(_scene(), "shot")
    sync.attach("shot", caller)
    written: list[str] = []
    write = records.write

    def counted(id_: bpy.types.ID, key: str, *args: object) -> None:
        written.append(key)
        write(id_, key, *args)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr(records, "write", counted)
    assert sync.attach("shot", caller).attached == (handle.binding_id,)
    assert handle.set_settings() == Result(ResultState.SUCCESS)
    assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_ALL) == Result(ResultState.SUCCESS)  # the default
    assert written == []
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert written == [bindings.config_key(handle.binding_id)]


def test_unavailable_source_is_a_result(sync: Synchronization, tmp_path: Path) -> None:
    # A file that won't open, and a binding with nothing attached: fatal-failure results, not exceptions.
    for handle in (
        sync.create_file_binding(_scene(), tmp_path / "missing.usda"),
        sync.create_attached_binding(_scene(), "shot"),
    ):
        for result in (handle.synchronize(0), handle.reload()):
            assert result.state == ResultState.FATAL_FAILURE
            assert [(d.category, d.severity) for d in result.diagnostics] == [
                (Category.UNAVAILABLE_SOURCE, Severity.ERROR)
            ]


def test_dirty_layers_are_reported_as_source_state(sync: Synchronization, tmp_path: Path) -> None:
    # The informational diagnostic names the dirty contributing layers and leaves the state success.
    with source_access.dirty_layer(tmp_path) as scene:
        result = sync.create_file_binding(_scene(), scene.root).synchronize(0)
        assert result.state == ResultState.SUCCESS
        [diagnostic] = result.diagnostics
        assert (diagnostic.category, diagnostic.severity) == (Category.SOURCE_STATE, Severity.INFO)
        assert {Path(layer) for layer in diagnostic.layers} == set(scene.dirty_contributing.values())


def test_reload_doesnt_synchronize(sync: Synchronization, tmp_path: Path) -> None:
    # The reload rereads the layers; the requested settings are as they were, and the next synchronize shows it.
    with source_access.dirty_layer(tmp_path) as scene:
        handle = sync.create_file_binding(_scene(), scene.root)
        handle.synchronize(1)
        before = handle.requested_settings()
        assert handle.reload() == Result(ResultState.SUCCESS)
        assert handle.requested_settings() == before
        assert handle.synchronize(1) == Result(ResultState.SUCCESS)  # nothing dirty left
        stage = handle.live_stage()
        assert stage is not None
        assert read_values(stage) == scene.disk_values


def test_reload_rejects_other_layers(sync: Synchronization, tmp_path: Path) -> None:
    handle = sync.create_file_binding(_scene(), _root(tmp_path))
    with pytest.raises(ValueError, match="Not contributing layers"):
        handle.reload([str(tmp_path / "unknown.usda")])


def test_attaching_under_a_key(sync: Synchronization, tmp_path: Path) -> None:
    root = _root(tmp_path)
    caller = open_fresh(root)
    handle = sync.create_attached_binding(_scene(), "shot")
    assert sync.attach("shot", caller).attached == (handle.binding_id,)
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    assert handle.live_stage() == caller


def test_releasing_under_a_key(sync: Synchronization, tmp_path: Path) -> None:
    # SRC-02: release(key) leaves every binding with the key unattached; others keep their stage.
    caller = open_fresh(_root(tmp_path))
    first, second = (sync.create_attached_binding(_scene(), "shot") for _ in range(2))
    other = sync.create_attached_binding(_scene(), "other")
    sync.attach("shot", caller)
    sync.attach("other", caller)
    for handle in (first, second, other):
        assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    assert sync.release("shot") == (first.binding_id, second.binding_id)
    for handle in (first, second):
        assert handle.live_stage() is None
        assert [d.category for d in handle.synchronize(0).diagnostics] == [Category.UNAVAILABLE_SOURCE]
    assert other.live_stage() == caller
    assert sync.attach("shot", caller).attached == (first.binding_id, second.binding_id)  # attachable again
    assert first.synchronize(0) == Result(ResultState.SUCCESS)


def test_undoing_a_file_bindings_creation_drops_its_stage(sync: Synchronization, tmp_path: Path) -> None:
    # The undo handler prunes at once; redo brings the binding back, and its next synchronization reopens.
    undo.require_global_undo()
    undo.push("base")
    handle = sync.create_file_binding(_scene(), _root(tmp_path))
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    undo.push("create")
    undo.undo()
    assert handle.binding_id not in sync.sources
    undo.redo()
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    assert handle.live_stage() is not None


def _counted_scans(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """One item for every time the bindings' state is rebuilt from the scenes' records from here on."""
    scans: list[int] = []
    all_bindings = bindings.all_bindings

    def counted() -> object:
        scans.append(1)
        return all_bindings()

    monkeypatch.setattr(bindings, "all_bindings", counted)
    return scans


def test_an_undo_with_no_sources_rebuilds_nothing_in_its_handler(
    sync: Synchronization, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bindings exist, but none has been synchronized this session: nothing to prune.
    undo.require_global_undo()
    handle = sync.create_file_binding(_scene(), _root(tmp_path))
    undo.push("base")
    bpy.data.objects.new("Unrelated", None)
    undo.push("edit")
    scans = _counted_scans(monkeypatch)
    undo.undo()
    assert scans == []
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)  # the next call rebuilds the state, once
    assert scans == [1]
    undo.redo()  # now with a source: pruned at once
    assert scans == [1, 1]


def test_pruning_compares_the_scenes_once(
    sync: Synchronization, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handles = [sync.create_file_binding(_scene(), _root(tmp_path / str(i)), name=f"B{i}") for i in range(3)]
    for handle in handles:
        handle.synchronize(0)
    current, calls = state.current_state, []  # the cost under test is one comparison of the scenes

    def counted() -> object:
        calls.append(1)
        return current()

    monkeypatch.setattr(state, "current_state", counted)
    sync.prune()
    assert len(calls) == 1
    assert all(handle.binding_id in sync.sources for handle in handles)


def test_undoing_an_attached_bindings_creation_keeps_its_attachment(sync: Synchronization, tmp_path: Path) -> None:
    # UNDO-06: undo neither restores nor removes attachments. The binding's evaluation stage goes; the
    # attachment stays for redo, and release(key) still releases it while the binding doesn't exist.
    undo.require_global_undo()
    caller = open_fresh(_root(tmp_path))
    undo.push("base")
    handle = sync.create_attached_binding(_scene(), "shot")
    sync.attach("shot", caller)
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    source = sync.sources.get(handle.binding_id)
    assert source is not None
    undo.push("create")
    undo.undo()
    assert source.evaluation_stage is None
    assert source.live_stage == caller
    undo.redo()
    assert handle.live_stage() == caller
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    undo.undo()
    assert sync.release("shot") == ()  # no binding with the key exists
    assert source.live_stage is None


def test_a_removed_scenes_file_binding_is_pruned(sync: Synchronization, tmp_path: Path) -> None:
    # No handler announces the removal: the next call that uses sources compares them with the bindings.
    scene = _scene()
    other = bpy.data.scenes.new("Other")  # sorts first: _scene() would return it
    removed = sync.create_file_binding(other, _root(tmp_path))
    kept = sync.create_file_binding(scene, _root(tmp_path))
    for handle in (removed, kept):
        assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    bpy.data.scenes.remove(other)
    assert kept.synchronize(0) == Result(ResultState.SUCCESS)
    assert removed.binding_id not in sync.sources
    assert kept.binding_id in sync.sources


def test_a_file_binding_whose_configuration_cant_be_read_is_pruned(sync: Synchronization, tmp_path: Path) -> None:
    handle = sync.create_file_binding(_scene(), _root(tmp_path))
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)
    _scene()[records.NAMESPACE][bindings.config_key(handle.binding_id)][records.VERSION_KEY] = 99
    runtime.invalidate()  # as a load, undo, or redo that restored this record would
    assert handle.synchronize(0).state == ResultState.FATAL_FAILURE  # unsupported, and pruned
    assert handle.binding_id not in sync.sources


def test_live_stage_through_the_handle(sync: Synchronization, tmp_path: Path) -> None:
    # F-CACHED-STAGE "ambient-cache", ICON-34: the handle's live stage is the binding's own source stage,
    # in no stage cache and not the ambient stage.
    with source_access.cached_stage(tmp_path) as scene:
        handle = sync.create_file_binding(_scene(), scene.root)
        assert handle.live_stage() is None  # no live stage before the first synchronization
        handle.synchronize(0)
        live = handle.live_stage()
        assert live is not None
        assert live != scene.ambient
        assert not UsdUtils.StageCache.Get().Contains(live)


def test_a_handle_to_no_binding_raises(sync: Synchronization) -> None:
    handle = BindingHandle("not-a-binding")
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
