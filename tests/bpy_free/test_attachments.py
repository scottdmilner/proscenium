"""An attached binding's stages in the runtime registry: held until released or replaced (SRC-02).

The attachment contract reads the binding records, so its tests are in tests/blender/test_bindings.py.
"""

from __future__ import annotations

import gc
import time
from typing import TYPE_CHECKING

import pytest
from pxr import Sdf, Usd

from fixtures import source_access
from proscenium.binding.source_access import BindingId
from proscenium.binding.source_access.binding_settings import PayloadPolicy
from proscenium.binding.source_access.stage_registry import StageRegistry
from proscenium.binding.source_access.stages import SourceUnavailableError
from support.usd import open_stage_without_cache

if TYPE_CHECKING:
    from pathlib import Path

# Expiry can lag a release, by up to 50 ms in M1b's runs (runtime-record.md, M1b Phase C).
EXPIRY_WAIT = 2.0


def test_the_binding_holds_its_attached_stage_until_released(tmp_path: Path) -> None:
    # Dropping the caller's references releases nothing: the stage and its unsaved edits stay loaded.
    # release(binding_id) lets the stage expire and its layers go, and leaves the binding unattached.
    registry = StageRegistry()
    stages = registry.get_or_create_binding_stages(BindingId("a"))
    with source_access.reattach(tmp_path) as scene:
        caller = open_stage_without_cache(
            scene.root_layer_path
        )  # this test's own stage, so it holds the only caller reference
        caller.SetEditTarget(caller.GetSessionLayer())
        caller.DefinePrim("/Edited")  # an unsaved edit in a layer only this stage composes
        session = caller.GetSessionLayer().identifier
        stages.attach(caller)
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        del caller
        gc.collect()
        assert stages.live_stage is not None
        layer = Sdf.Layer.Find(session)
        assert layer is not None and layer.GetPrimAtPath("/Edited") is not None
        del layer
        registry.release(BindingId("a"))
        deadline = time.monotonic() + EXPIRY_WAIT
        while Sdf.Layer.Find(session) and time.monotonic() < deadline:  # the session layer goes with its stage
            gc.collect()
            time.sleep(0.01)
        assert not Sdf.Layer.Find(session)
        assert stages.live_stage is None
        with pytest.raises(SourceUnavailableError):
            stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)


@pytest.mark.parametrize("changed_layer", ["root", "session"])
def test_attaching_another_stage_lets_go_of_the_evaluation_stage(tmp_path: Path, changed_layer: str) -> None:
    # The binding holds its attachment until released or replaced (SRC-02): replacing it lets go of the
    # evaluation stage over the old stage's layers at once, and reattaching the same stage keeps it.
    with source_access.reattach(tmp_path) as scene:
        stages = StageRegistry().get_or_create_binding_stages(BindingId("a"))
        stages.attach(scene.caller)
        evaluation = stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        stages.attach(scene.caller)
        assert stages.evaluation_stage == evaluation
        if changed_layer == "root":
            with Usd.StageCacheContext(Usd.BlockStageCaches):
                replacement = Usd.Stage.Open(scene.other_root.GetRootLayer(), scene.caller.GetSessionLayer())
        else:
            replacement = scene.same_root
        stages.attach(replacement)
        assert stages.evaluation_stage is None
        assert stages.live_stage == replacement
        refreshed = stages.acquire_evaluation_stage(PayloadPolicy.LOAD_NONE)
        assert refreshed != evaluation
        assert refreshed.GetRootLayer() == replacement.GetRootLayer()
        assert refreshed.GetSessionLayer() == replacement.GetSessionLayer()
        assert not refreshed.GetLoadSet()


def test_attaching_another_stage_over_the_same_layers_reuses_evaluation(tmp_path: Path) -> None:
    # SRC-10: evaluation belongs to the root and session layers, independently of the source stage's identity.
    with source_access.reattach(tmp_path) as scene:
        stages = StageRegistry().get_or_create_binding_stages(BindingId("a"))
        stages.attach(scene.caller)
        evaluation = stages.acquire_evaluation_stage(PayloadPolicy.LOAD_NONE)
        with Usd.StageCacheContext(Usd.BlockStageCaches):
            replacement = Usd.Stage.Open(scene.caller.GetRootLayer(), scene.caller.GetSessionLayer())
        assert replacement != scene.caller
        stages.attach(replacement)
        assert stages.live_stage == replacement
        assert stages.evaluation_stage == evaluation
        assert stages.acquire_evaluation_stage(PayloadPolicy.LOAD_NONE) == evaluation
        assert replacement.GetLoadSet()
        assert not evaluation.GetLoadSet()
