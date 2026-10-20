"""The synchronization API's entry point, acquisition only (source-access.md#synchronization-api).

Through binding handles over a fresh process state per test, on bindings in the factory scene.
Their records, save/reopen, undo, and the key contract are in test_bindings.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import bpy
import pytest
from pxr import Usd, UsdUtils

from fixtures import source_access
from fixtures.scenes import Scene, copy_scene
from fixtures.source_access import DISK, read_values
from proscenium import synchronization
from proscenium.synchronization import (
    BindingHandle,
    BindingNotFound,
    Category,
    Result,
    ResultState,
    Severity,
    Synchronization,
)
from support.usd import open_fresh

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def sync(monkeypatch: pytest.MonkeyPatch) -> Generator[Synchronization]:
    """A fresh process state, which handles use."""
    fresh = Synchronization()
    monkeypatch.setattr(synchronization, "SYNCHRONIZATION", fresh)
    yield fresh


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
    handle = sync.create_file_binding(_scene(), _root(tmp_path), payload_policy=Usd.Stage.LoadNone)
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
    assert handle.set_settings(payload_policy=Usd.Stage.LoadNone) == Result(ResultState.SUCCESS)
    assert handle.requested_settings().payload_policy == Usd.Stage.LoadNone
    assert read_values(stage) == DISK  # not applied yet
    handle.synchronize(3)
    assert read_values(stage) == DISK | {"payA": None, "payB": None}


def test_set_settings_before_the_first_synchronization_opens_nothing(sync: Synchronization, tmp_path: Path) -> None:
    handle = sync.create_file_binding(_scene(), _root(tmp_path))
    handle.set_settings(payload_policy=Usd.Stage.LoadNone)
    assert handle.live_stage() is None


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
        lambda: handle.set_settings(payload_policy=Usd.Stage.LoadNone),
        handle.reload,
        handle.requested_settings,
        handle.live_stage,
    ]
    for call in calls:
        with pytest.raises(BindingNotFound):
            call()
