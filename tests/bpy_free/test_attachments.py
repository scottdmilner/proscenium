"""An attached binding's stages in the runtime registry: held until released or replaced (SRC-02).

The key contract reads the binding records, so its tests are in tests/blender/test_bindings.py.
"""

from __future__ import annotations

import gc
import time
from typing import TYPE_CHECKING

import pytest
from pxr import Sdf

from fixtures import source_access
from proscenium.core.binding_ids import BindingId
from proscenium.core.source_access import PayloadPolicy, SourceUnavailableError, StageRegistry
from support.usd import open_fresh

if TYPE_CHECKING:
    from pathlib import Path

# Expiry can lag a release, by up to 50 ms in M1b's runs (runtime-record.md, M1b Phase C).
EXPIRY_WAIT = 2.0


def test_the_binding_holds_its_attached_stage_until_released(tmp_path: Path) -> None:
    # Dropping the caller's references releases nothing: the stage and its unsaved edits stay loaded.
    # release(key) lets the stage expire and its layers go, and leaves the binding unattached.
    registry = StageRegistry()
    stages = registry.attached(BindingId("a"), "shot")
    with source_access.reattach(tmp_path) as scene:
        caller = open_fresh(scene.root)  # this test's own stage, so it holds the only caller reference
        caller.SetEditTarget(caller.GetSessionLayer())
        caller.DefinePrim("/Edited")  # an unsaved edit in a layer only this stage composes
        session = caller.GetSessionLayer().identifier
        stages.attach(caller)
        stages.acquire(PayloadPolicy.LOAD_ALL)
        del caller
        gc.collect()
        assert stages.live_stage is not None
        layer = Sdf.Layer.Find(session)
        assert layer is not None and layer.GetPrimAtPath("/Edited") is not None
        del layer
        registry.release("shot")
        deadline = time.monotonic() + EXPIRY_WAIT
        while Sdf.Layer.Find(session) and time.monotonic() < deadline:  # the session layer goes with its stage
            gc.collect()
            time.sleep(0.01)
        assert not Sdf.Layer.Find(session)
        assert stages.live_stage is None
        with pytest.raises(SourceUnavailableError):
            stages.acquire(PayloadPolicy.LOAD_ALL)


def test_attaching_another_stage_lets_go_of_the_evaluation_stage(tmp_path: Path) -> None:
    # The binding holds its attachment until released or replaced (SRC-02): replacing it lets go of the
    # evaluation stage over the old stage's layers at once, and reattaching the same stage keeps it.
    with source_access.reattach(tmp_path) as scene:
        stages = StageRegistry().attached(BindingId("a"), "shot")
        stages.attach(scene.caller)
        evaluation = stages.acquire(PayloadPolicy.LOAD_ALL)
        stages.attach(scene.caller)
        assert stages.evaluation_stage == evaluation
        stages.attach(scene.same_root)  # the same root layer, another session layer
        assert stages.evaluation_stage is None
        assert stages.live_stage == scene.same_root
