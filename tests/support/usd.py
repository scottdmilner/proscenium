"""USD helpers for tests: opening stages that no stage cache can share.

To use a static scene from tests/fixtures/scenes/, copy it first with
fixtures.scenes.copy_scene.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pxr import Usd

from proscenium.core.source_access import PayloadPolicy

if TYPE_CHECKING:
    from pathlib import Path

    import bpy

    from proscenium.api.bindings import BindingHandle, Bindings


def open_fresh(path: Path, load: Any = Usd.Stage.LoadAll) -> Usd.Stage:
    """Open a new stage for `path`, even if a stage cache context is active.

    Inside an active Usd.StageCacheContext, Usd.Stage.Open can return an
    existing cached stage (runtime-record.md#in-memory-source-candidates).
    """
    with Usd.StageCacheContext(Usd.BlockStageCaches):
        return Usd.Stage.Open(str(path), load)


def binding_on_file(
    bindings: Bindings,
    scene: bpy.types.Scene,
    root: Path,
    *,
    payload_policy: PayloadPolicy = PayloadPolicy.LOAD_ALL,
    name: str | None = None,
) -> BindingHandle:
    """Open a copied fixture and attach its stage to a binding with an independent source key."""
    stage = open_fresh(root)
    key = uuid4().hex
    handle = bindings.create_binding(scene, key, payload_policy=payload_policy, name=name or root.stem)
    bindings.attach(key, stage)
    return handle
