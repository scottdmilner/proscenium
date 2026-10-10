"""USD helpers for tests: opening stages that no stage cache can share.

To use a static scene from tests/fixtures/scenes/, copy it first with
fixtures.scenes.copy_scene.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pxr import Usd

if TYPE_CHECKING:
    from pathlib import Path


def open_fresh(path: Path, load: Any = Usd.Stage.LoadAll) -> Usd.Stage:
    """Open a new stage for `path`, even if a stage cache context is active.

    Inside an active Usd.StageCacheContext, Usd.Stage.Open can return an
    existing cached stage (runtime-record.md#in-memory-source-candidates).
    """
    with Usd.StageCacheContext(Usd.BlockStageCaches):
        return Usd.Stage.Open(str(path), load)
