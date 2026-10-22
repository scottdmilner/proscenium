"""Every binding's source stage in the runtime registry, and the attached stage as the live stage (ICON-07).

The key contract reads the binding records, so its tests are in tests/blender/test_bindings.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fixtures import source_access
from proscenium.core.source_access import AttachedSource, PayloadPolicy, StageRegistry

if TYPE_CHECKING:
    from pathlib import Path


def test_live_stage_is_the_attached_stage(tmp_path: Path) -> None:
    # ICON-07: the live stage is the caller's attached stage, not the evaluation stage.
    with source_access.reattach(tmp_path) as scene:
        registry = StageRegistry()
        stages = registry.attached("a", "shot")
        assert isinstance(stages.source, AttachedSource)
        stages.source.attach(scene.caller)
        evaluation = stages.acquire(PayloadPolicy.LOAD_ALL)
        assert stages.live_stage == scene.caller
        assert evaluation != scene.caller


def test_attaching_another_stage_lets_go_of_the_evaluation_stage(tmp_path: Path) -> None:
    # The binding holds its attachment until released or replaced (SRC-02): replacing it lets go of the
    # evaluation stage over the old stage's layers at once, and reattaching the same stage keeps it.
    with source_access.reattach(tmp_path) as scene:
        stages = StageRegistry().attached("a", "shot")
        stages.attach(scene.caller)
        evaluation = stages.acquire(PayloadPolicy.LOAD_ALL)
        stages.attach(scene.caller)
        assert stages.evaluation_stage == evaluation
        stages.attach(scene.same_root)  # the same root layer, another session layer
        assert stages.evaluation_stage is None
        assert stages.live_stage == scene.same_root
