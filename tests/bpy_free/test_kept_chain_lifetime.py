"""The scene-index chain a binding keeps over its evaluation stage, and what releases it (M7 plan, C1; SRC-02).

On F-SOURCE-CHANGE's scene, with the core's chain kept through BindingStages.keep_chain, as evaluation keeps it. A
chain outlives what its stage's notices carry, edits and a reattachment over the same layers, and is released by every
change the plan names, so the next capture is from a new chain. tests/blender/test_kept_chain_use.py checks that
synchronizations and cache calls share it.
"""

from __future__ import annotations

import gc
import time
from typing import TYPE_CHECKING

import pytest
from pxr import Sdf, Usd

from fixtures import transaction
from proscenium.binding.source_access import BindingId
from proscenium.binding.source_access.binding_settings import PayloadPolicy
from proscenium.binding.source_access.stage_registry import StageRegistry
from proscenium.binding.source_access.stages import BindingStages, SourceUnavailableError
from proscenium.core import _core

from . import plan_serialization
from .attached_binding_stages import binding

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from fixtures.transaction import SourceChangeScene

SETTINGS = _core.PlanSettings(("default", "proxy"), ("default", "render"), coordinate_conversion=False)
CONTEXT = _core.PlanningContext(1.0, 1)
EXPIRY_WAIT = 2.0  # expiry can lag a release, by up to 50 ms in M1b's runs (runtime-record.md, M1b Phase C)


def _keep(stages: BindingStages) -> _core.SceneIndexChain:
    """A chain over the binding's evaluation stage under LOAD_ALL, kept and captured from once."""
    chain = _core.SceneIndexChain(stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL))
    stages.keep_chain(chain)
    chain.capture(Usd.TimeCode(0))
    return chain


def _planned(chain: _core.SceneIndexChain) -> dict[str, object]:
    return plan_serialization.contents(_core.plan(chain.capture(Usd.TimeCode(0)), SETTINGS, CONTEXT))


def _sub(scene: SourceChangeScene) -> str:
    return Sdf.Layer.Find(str(scene.sub_layer)).identifier


def test_a_kept_chain_follows_edits_and_reattachment(tmp_path: Path) -> None:
    # An acquisition that matches nothing new, an edit to a contributing layer, and the stage attached again over the
    # same layers keep the chain, and it then plans what a new chain over the edited stage plans.
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        chain = _keep(stages)
        before = _planned(chain)
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        scene.edit()
        stages.attach(scene.caller)
        evaluation_stage = stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        assert stages.kept_chain is chain
        assert not chain.released
        fresh = _core.SceneIndexChain(evaluation_stage)
        try:
            assert _planned(chain) == _planned(fresh) != before
        finally:
            fresh.release()
            stages.release()


def _release(stages: BindingStages, _scene: SourceChangeScene) -> None:
    stages.release()


def _drop(stages: BindingStages, _scene: SourceChangeScene) -> None:
    stages.drop_evaluation_stage()


def _attach_another_root(stages: BindingStages, _scene: SourceChangeScene) -> None:
    stages.attach(Usd.Stage.CreateInMemory())


def _payload_policy(stages: BindingStages, _scene: SourceChangeScene) -> None:
    stages.acquire_evaluation_stage(PayloadPolicy.LOAD_NONE)


def _reload(stages: BindingStages, _scene: SourceChangeScene) -> None:
    stages.reload(PayloadPolicy.LOAD_ALL)  # nothing on disk changed, so nothing is reread


def _reload_one(stages: BindingStages, scene: SourceChangeScene) -> None:
    stages.reload(PayloadPolicy.LOAD_ALL, [_sub(scene)])


def _mute(stages: BindingStages, scene: SourceChangeScene) -> None:
    scene.caller.MuteLayer(_sub(scene))
    stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)


def _hold_values(stages: BindingStages, scene: SourceChangeScene) -> None:
    scene.caller.SetInterpolationType(Usd.InterpolationTypeHeld)
    stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)


def _mask(stages: BindingStages, scene: SourceChangeScene) -> None:
    scene.caller.SetPopulationMask(Usd.StagePopulationMask(["/World/Sub"]))
    stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)


RELEASING: dict[str, Callable[[BindingStages, SourceChangeScene], None]] = {
    "release": _release,
    "drop": _drop,
    "another root": _attach_another_root,
    "payload policy": _payload_policy,
    "reload": _reload,
    "reload one layer": _reload_one,
    "muting": _mute,
    "interpolation": _hold_values,
    "mask": _mask,
}


@pytest.mark.parametrize("change", RELEASING.values(), ids=RELEASING.keys())
def test_a_change_the_chain_isnt_vouched_to_follow_releases_it(
    change: Callable[[BindingStages, SourceChangeScene], None], tmp_path: Path
) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        chain = _keep(stages)
        change(stages, scene)
        assert chain.released
        assert stages.kept_chain is None
        stages.release()


def test_a_refused_reload_keeps_the_chain(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        chain = _keep(stages)
        with pytest.raises(ValueError, match="Not contributing layers"):
            stages.reload(PayloadPolicy.LOAD_ALL, ["unknown.usda"])
        assert stages.kept_chain is chain
        assert not chain.released
        stages.release()


def test_a_released_bindings_evaluation_stage_expires(tmp_path: Path) -> None:
    # SRC-02's part for the kept chain: once the binding releases, nothing keeps its evaluation stage, though the
    # caller still holds its own stage over the same layers.
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        chain = _keep(stages)
        assert chain.stage() is not None
        stages.release()
        deadline = time.monotonic() + EXPIRY_WAIT
        while chain.stage() is not None and time.monotonic() < deadline:
            gc.collect()
            time.sleep(0.01)
        assert chain.stage() is None
        assert scene.caller.GetPseudoRoot()


def test_keeping_another_chain_releases_the_first(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        first = _keep(stages)
        stages.keep_chain(first)  # keeping it again keeps it
        assert not first.released
        second = _keep(stages)
        assert first.released
        assert stages.kept_chain is second
        stages.release()


def test_a_chain_is_kept_only_over_an_evaluation_stage(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        chain = _core.SceneIndexChain(scene.caller)
        try:
            with pytest.raises(SourceUnavailableError):
                stages.keep_chain(chain)
            assert stages.kept_chain is None
        finally:
            chain.release()


@pytest.mark.parametrize("step", ["prune", "release all"])
def test_the_registry_releases_kept_chains(step: str, tmp_path: Path) -> None:
    # Pruning a vanished binding, as after an undo of its creation, and dropping every binding, as on a file load.
    with transaction.source_change(tmp_path) as scene:
        registry = StageRegistry()
        stages = registry.get_or_create_binding_stages(BindingId("gone"))
        stages.attach(scene.caller)
        chain = _keep(stages)
        if step == "prune":
            registry.prune(())
            assert stages.live_stage == scene.caller  # the attachment stays for redo (UNDO-06)
        else:
            registry.release_all()
            assert registry.get(BindingId("gone")) is None
        assert chain.released
        assert stages.kept_chain is None
        stages.release()
