"""An attached source stage and its independent evaluation stage (SRC-02 to SRC-10)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Usd, UsdUtils

from fixtures import source_access
from fixtures.scenes import Scene, copy_scene
from fixtures.source_access import DISK, caller_settings, layer_contents, read_values
from proscenium.core.source_access import (
    BindingStages,
    PayloadPolicy,
    SourceUnavailableError,
)
from support.usd import open_fresh

from .bindings import binding

if TYPE_CHECKING:
    from pathlib import Path

UNLOADED = {"payA": None, "payB": None}
POLICIES = tuple(PayloadPolicy)


def _caller(tmp_path: Path) -> Usd.Stage:
    """A copy of the source-access scene and a caller's stage over it, which an attached binding uses."""
    root = copy_scene(Scene.SOURCE_ACCESS, tmp_path) / "root.usda"
    return open_fresh(root)


def _set_root_value_in_session(stage: Usd.Stage, value: float) -> None:
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        stage.GetPrimAtPath("/World").GetAttribute("rootValue").Set(value)


# --- every binding ------------------------------------------------------------------------------


def test_evaluation_stage_is_kept_and_reused(tmp_path: Path) -> None:
    caller = _caller(tmp_path)
    source = binding(caller)
    assert source.evaluation_stage is None
    stage = source.acquire(PayloadPolicy.LOAD_ALL)
    assert source.evaluation_stage == stage
    assert source.acquire(PayloadPolicy.LOAD_ALL) == stage


def test_live_stage_is_the_source_stage(tmp_path: Path) -> None:
    caller = _caller(tmp_path)
    source = binding(caller)
    assert source.live_stage == caller  # ICON-07: available before evaluation
    stage = source.acquire(PayloadPolicy.LOAD_ALL)
    assert source.live_stage == caller
    assert stage != caller


def test_session_layer_opinions_are_displayed(tmp_path: Path) -> None:
    # SRC-05: opinions in the source stage's session layer compose over the source.
    caller = _caller(tmp_path)
    source = binding(caller)
    source.acquire(PayloadPolicy.LOAD_ALL)
    live = source.live_stage
    assert live is not None
    _set_root_value_in_session(live, 4.0)
    assert read_values(source.acquire(PayloadPolicy.LOAD_ALL)) == DISK | {"root": 4.0}


def test_unavailable_source() -> None:
    source = BindingStages("shot")
    with pytest.raises(SourceUnavailableError):
        source.acquire(PayloadPolicy.LOAD_ALL)
    assert source.evaluation_stage is None
    assert source.live_stage is None


def test_a_changed_payload_policy_applies_to_the_reused_stage(tmp_path: Path) -> None:
    caller = _caller(tmp_path)
    source = binding(caller)
    stage = source.acquire(PayloadPolicy.LOAD_ALL)
    assert source.acquire(PayloadPolicy.LOAD_NONE) == stage  # the same stage, its payloads unloaded
    assert read_values(stage) == DISK | UNLOADED
    assert source.acquire(PayloadPolicy.LOAD_ALL) == stage
    assert read_values(stage) == DISK
    assert read_values(caller) == DISK  # an attached caller's load set is its own


def test_a_reload_leaves_the_payload_policy(tmp_path: Path) -> None:
    # The policy given only opens a stage when there is none; a reload doesn't synchronize.
    caller = _caller(tmp_path)
    source = binding(caller)
    stage = source.acquire(PayloadPolicy.LOAD_ALL)
    source.reload(PayloadPolicy.LOAD_NONE)
    assert read_values(stage) == DISK


def test_switching_payload_policy_and_back_keeps_the_display(tmp_path: Path) -> None:
    # Metamorphic: load-all, then load-none again, composes what the binding showed before,
    # session-layer opinions included, and changes no layer.
    caller = _caller(tmp_path)
    source = binding(caller)
    stage = source.acquire(PayloadPolicy.LOAD_NONE)
    live = source.live_stage
    assert live is not None
    _set_root_value_in_session(live, 4.0)
    before = read_values(source.acquire(PayloadPolicy.LOAD_NONE))
    for policy in (PayloadPolicy.LOAD_ALL, PayloadPolicy.LOAD_NONE):
        source.acquire(policy)
    assert read_values(stage) == before
    assert not [layer.identifier for layer in stage.GetUsedLayers() if layer.dirty and not layer.anonymous]


# --- cache isolation ---------------------------------------------------------------------------


def test_ambient_cache(tmp_path: Path) -> None:
    # F-CACHED-STAGE: the caller opens a source whose session opinions differ from the cached stage's.
    with source_access.cached_stage(tmp_path) as scene:
        ambient_settings = caller_settings(scene.ambient)
        caller = open_fresh(scene.root)
        source = binding(caller)
        stage = source.acquire(PayloadPolicy.LOAD_ALL)
        assert stage != caller and stage != scene.ambient
        assert source.live_stage == caller
        assert not UsdUtils.StageCache.Get().Contains(stage)
        assert read_values(stage) == scene.disk_values
        assert read_values(scene.ambient) == scene.ambient_values
        assert caller_settings(scene.ambient) == ambient_settings


# --- evaluation fidelity -----------------------------------------------------------------------


def _expected(scene: source_access.PrivateStageScene, payload_policy: PayloadPolicy) -> dict:
    # The caller's composed values, with payload content by the binding's policy: PayB is in the
    # caller's mask but its payload isn't loaded by the caller.
    loaded = 1.0 if payload_policy is PayloadPolicy.LOAD_ALL else None
    return scene.caller_values | {"payA": loaded, "payB": loaded}


def _stage_settings(stage: Usd.Stage) -> tuple[str, list[str], str]:
    return str(stage.GetPopulationMask()), sorted(stage.GetMutedLayers()), str(stage.GetInterpolationType())


def test_caller_settings(tmp_path: Path) -> None:
    # F-PRIVATE-STAGE "caller-settings", under each payload policy.
    with source_access.private_stage(tmp_path) as scene:
        caller = scene.caller
        for payload_policy in POLICIES:
            evaluation = binding(caller).acquire(payload_policy)
            # SRC-06: a separate stage composing the caller's own layers, in no cache, with its resolver context.
            assert evaluation != caller
            assert evaluation.GetRootLayer() == caller.GetRootLayer()
            assert evaluation.GetSessionLayer() == caller.GetSessionLayer()
            assert not UsdUtils.StageCache.Get().Contains(evaluation)
            assert evaluation.GetPathResolverContext() == caller.GetPathResolverContext()
            # SRC-05: the caller's composition, unsaved edit and session opinions included.
            assert read_values(evaluation) == _expected(scene, payload_policy)
            # SRC-07: mask, muting, and interpolation match; the held interpolation shows at time 5.
            assert _stage_settings(evaluation) == _stage_settings(caller)
            assert evaluation.GetPrimAtPath("/World").GetAttribute("animValue").Get(5) == scene.caller_anim_at_5
            # SRC-04: the caller's stage and layers are as they were.
            assert caller_settings(caller) == scene.settings
            assert layer_contents(caller) == scene.layers


def test_caller_settings_are_matched_at_each_acquisition(tmp_path: Path) -> None:
    # SRC-07: the caller changes its settings between synchronizations.
    with source_access.private_stage(tmp_path) as scene:
        caller = scene.caller
        source = binding(caller)
        evaluation = source.acquire(PayloadPolicy.LOAD_ALL)
        caller.SetPopulationMask(Usd.StagePopulationMask.All())
        caller.UnmuteLayer(caller.GetMutedLayers()[0])
        caller.SetInterpolationType(Usd.InterpolationTypeLinear)
        settings = caller_settings(caller)
        assert source.acquire(PayloadPolicy.LOAD_ALL) == evaluation  # reused
        assert _stage_settings(evaluation) == _stage_settings(caller)
        assert read_values(evaluation) == _expected(scene, PayloadPolicy.LOAD_ALL) | {"extra": 1.0, "outside": 1.0}
        assert evaluation.GetPrimAtPath("/World").GetAttribute("animValue").Get(5) == 5.0
        assert caller_settings(caller) == settings


def test_payload_policies(tmp_path: Path) -> None:
    # F-PRIVATE-STAGE "payload-policies" (SRC-08): load-all and load-none bindings side by side.
    with source_access.private_stage(tmp_path) as scene:
        caller = scene.caller
        load_set = caller.GetLoadSet()
        loading = binding(caller)
        unloading = binding(caller)
        loaded, unloaded = loading.acquire(PayloadPolicy.LOAD_ALL), unloading.acquire(PayloadPolicy.LOAD_NONE)
        loading.acquire(PayloadPolicy.LOAD_ALL)
        assert loaded != unloaded
        assert read_values(loaded) == _expected(scene, PayloadPolicy.LOAD_ALL)
        assert read_values(unloaded) == _expected(scene, PayloadPolicy.LOAD_NONE)
        assert caller.GetLoadSet() == load_set


def test_a_caller_with_other_layers_gets_a_new_evaluation_stage(tmp_path: Path) -> None:
    with source_access.private_stage(tmp_path) as scene:
        source = binding(scene.caller)
        first = source.acquire(PayloadPolicy.LOAD_ALL)
        other = open_fresh(scene.root)  # the same root layer, but its own session layer
        source.attach(other)
        second = source.acquire(PayloadPolicy.LOAD_ALL)
        assert second != first
        assert second.GetSessionLayer() == other.GetSessionLayer()


def test_evaluation_stage_is_not_the_cached_caller(tmp_path: Path) -> None:
    # SRC-06: with the caller cached and its cache context active, Open would return the caller itself.
    with source_access.private_stage(tmp_path) as scene:
        cache = UsdUtils.StageCache.Get()
        cache_id = cache.Insert(scene.caller)
        try:
            with Usd.StageCacheContext(cache):
                evaluation = binding(scene.caller).acquire(PayloadPolicy.LOAD_ALL)
            assert evaluation != scene.caller
            assert not cache.Contains(evaluation)
        finally:
            cache.Erase(cache_id)
