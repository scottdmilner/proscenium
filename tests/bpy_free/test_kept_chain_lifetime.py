"""The scene-index chain a binding keeps over its evaluation stage, and what releases it (M7 plan, C1; SRC-02).

With the planner's chain kept through BindingStages.keep_chain, as evaluation keeps it. A chain outlives what its
stage's notices carry: on F-SOURCE-CHANGE's scene, edits and a reattachment over the same layers; on F-EDIT-SEQUENCE's,
reloads and another payload policy, mask, muting, or interpolation, after each of which, and after an edit that follows,
it plans what a new chain plans (M7 plan, C3d). It's released with the evaluation stage, so the next capture is from a
new chain. tests/blender/test_kept_chain_use.py checks that synchronizations and cache calls share it.
"""

from __future__ import annotations

import gc
import time
from typing import TYPE_CHECKING

import pytest
from pxr import Sdf, Usd, UsdGeom

from fixtures import edit_sequence, transaction
from proscenium_sync import planner
from proscenium_sync.source_access import BindingId
from proscenium_sync.source_access.binding_settings import PayloadPolicy
from proscenium_sync.source_access.stage_registry import StageRegistry
from proscenium_sync.source_access.stages import BindingStages, SourceUnavailableError

from . import plan_serialization
from .attached_binding_stages import binding

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from fixtures.edit_sequence import EditSequenceScene
    from fixtures.transaction import SourceChangeScene

SETTINGS = planner.PlanSettings(("default", "proxy"), ("default", "render"), coordinate_conversion=False)
CONTEXT = planner.PlanningContext(1.0, 1)
EXPIRY_WAIT = 2.0  # expiry can lag a release, by up to 50 ms in M1b's runs (runtime-record.md, M1b Phase C)


def _keep(stages: BindingStages) -> planner.SceneIndexChain:
    """A chain over the binding's evaluation stage under LOAD_ALL, kept and captured from once."""
    chain = planner.SceneIndexChain(stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL))
    stages.keep_chain(chain)
    chain.capture(Usd.TimeCode(0))
    return chain


def _planned(chain: planner.SceneIndexChain) -> dict[str, object]:
    return plan_serialization.contents(planner.plan(chain.capture(Usd.TimeCode(0)), SETTINGS, CONTEXT))


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
        fresh = planner.SceneIndexChain(evaluation_stage)
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


RELEASING: dict[str, Callable[[BindingStages, SourceChangeScene], None]] = {
    "release": _release,
    "drop": _drop,
    "another root": _attach_another_root,
}


@pytest.mark.parametrize("change", RELEASING.values(), ids=RELEASING.keys())
def test_dropping_the_evaluation_stage_releases_the_chain(
    change: Callable[[BindingStages, SourceChangeScene], None], tmp_path: Path
) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        chain = _keep(stages)
        change(stages, scene)
        assert chain.released
        assert stages.kept_chain is None
        stages.release()


# A step changes the binding's source state; with the stage acquired again, it changes what a new chain plans.
type SourceStep = Callable[[BindingStages, EditSequenceScene], None]

AT = Usd.TimeCode(5)  # between Mover's samples, so interpolation changes its translation


def _acquire(stages: BindingStages, _scene: EditSequenceScene) -> None:
    stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)


def _caller_steps(*edits: Callable[[EditSequenceScene], object]) -> tuple[SourceStep, ...]:
    """A step per edit to the caller's stage, each followed by an acquisition, which matches it."""

    def step(edit: Callable[[EditSequenceScene], object]) -> SourceStep:
        def run(stages: BindingStages, scene: EditSequenceScene) -> None:
            edit(scene)
            _acquire(stages, scene)

        return run

    return tuple(step(edit) for edit in edits)


def _sub_layer(scene: EditSequenceScene) -> Sdf.Layer:
    layer = Sdf.Layer.Find(str(scene.sub_layer_path))
    assert layer is not None
    return layer


def _reload_rewritten(stages: BindingStages, scene: EditSequenceScene) -> None:
    scene.rewrite_far_on_disk()
    stages.reload(PayloadPolicy.LOAD_ALL)


def _reload_rewritten_layer(stages: BindingStages, scene: EditSequenceScene) -> None:
    scene.rewrite_far_on_disk()
    stages.reload(PayloadPolicy.LOAD_ALL, [_sub_layer(scene).identifier])


def _edit_far_in_memory(_stages: BindingStages, scene: EditSequenceScene) -> None:
    _sub_layer(scene).GetAttributeAtPath(f"{edit_sequence.FAR}.xformOp:translate").default = (6, 20, 0)


def _reload_discarding(stages: BindingStages, _scene: EditSequenceScene) -> None:
    stages.reload(PayloadPolicy.LOAD_ALL)  # discards the unsaved edit


def _reload_dropping_sub_layer(stages: BindingStages, scene: EditSequenceScene) -> None:
    scene.drop_sub_layer_on_disk()
    stages.reload(PayloadPolicy.LOAD_ALL)


def _payload_policy(policy: PayloadPolicy) -> SourceStep:
    def run(stages: BindingStages, _scene: EditSequenceScene) -> None:
        stages.acquire_evaluation_stage(policy)

    return run


def _hide_b_in_sub_layer(scene: EditSequenceScene) -> None:
    # An opinion the root layer lacks on a prim it defines, so muting the layer changes a copy that stays drawn.
    with Usd.EditContext(scene.stage, _sub_layer(scene)):
        UsdGeom.Imageable(scene.stage.GetPrimAtPath(edit_sequence.B)).MakeInvisible()


def _mute(scene: EditSequenceScene) -> None:
    scene.stage.MuteLayer(_sub_layer(scene).identifier)


def _unmute(scene: EditSequenceScene) -> None:
    [muted] = scene.stage.GetMutedLayers()
    scene.stage.UnmuteLayer(muted)


FOLLOWED: dict[str, tuple[SourceStep, ...]] = {
    "reload": (_reload_rewritten,),
    "reload one layer": (_reload_rewritten_layer,),
    "reload discarding an unsaved edit": (_edit_far_in_memory, _reload_discarding),
    "reload changing composition": (_reload_dropping_sub_layer,),
    # USD's default traversal skips an unloaded prim, so a policy change only removes or adds the payloads' prims.
    "payload policy": (_payload_policy(PayloadPolicy.LOAD_NONE), _payload_policy(PayloadPolicy.LOAD_ALL)),
    "mask": _caller_steps(
        lambda scene: scene.stage.SetPopulationMask(Usd.StagePopulationMask([edit_sequence.GROUP])),
        lambda scene: scene.stage.SetPopulationMask(Usd.StagePopulationMask.All()),
    ),
    "muting": _caller_steps(_hide_b_in_sub_layer, _mute, _unmute),
    "interpolation": _caller_steps(
        lambda scene: scene.stage.SetInterpolationType(Usd.InterpolationTypeHeld),
        lambda scene: scene.stage.SetInterpolationType(Usd.InterpolationTypeLinear),
    ),
}


def _planned_at(chain: planner.SceneIndexChain) -> dict[str, object]:
    return plan_serialization.contents(planner.plan(chain.capture(AT), SETTINGS, CONTEXT))


def _new_chain_plan(stages: BindingStages) -> dict[str, object]:
    assert stages.evaluation_stage is not None
    fresh = planner.SceneIndexChain(stages.evaluation_stage)
    try:
        return _planned_at(fresh)
    finally:
        fresh.release()


@pytest.mark.parametrize("steps", FOLLOWED.values(), ids=FOLLOWED.keys())
def test_a_kept_chain_follows_reloads_and_acquired_settings(steps: tuple[SourceStep, ...], tmp_path: Path) -> None:
    # Each step changes the plan, and the kept chain's equals a new chain's, then again after an edit that follows.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        stages = binding(scene.stage)
        chain = _keep(stages)
        before = _planned_at(chain)
        try:
            for step in steps:
                step(stages, scene)
                assert stages.kept_chain is chain
                expected = _new_chain_plan(stages)
                assert _planned_at(chain) == expected != before
                before = expected
            scene.stage.GetAttributeAtPath(f"{edit_sequence.A}.xformOp:translate").Set((0, 0, 2))
            _acquire(stages, scene)
            assert _planned_at(chain) == _new_chain_plan(stages) != before
        finally:
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
        chain = planner.SceneIndexChain(scene.caller)
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
