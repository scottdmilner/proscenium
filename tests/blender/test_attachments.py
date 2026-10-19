"""Undo neither restores nor removes attachments of callers' stages (UNDO-06).

The registry is Python state outside Blender data. The binding records that undo
changes come with M3 Phase D, so here undo and redo change a scene property.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
from pxr import Usd

from fixtures import source_access
from proscenium.core.source_access import SourceRegistry
from support import undo

if TYPE_CHECKING:
    from pathlib import Path


def test_undo_and_redo_leave_attachments(tmp_path: Path) -> None:
    undo.require_global_undo()
    registry = SourceRegistry()
    binding = registry.add_attached("a", "shot", Usd.Stage.LoadAll)
    with source_access.reattach(tmp_path) as scene:
        registry.attach("shot", scene.caller)
        undo.push("base")
        _scene().frame_current = 7
        undo.push("change")
        undo.undo()
        assert _scene().frame_current != 7  # undone
        assert registry.get("a") is binding  # found by binding identity
        assert binding.live_stage == scene.caller
        undo.redo()
        assert _scene().frame_current == 7
        assert registry.get("a") is binding
        assert binding.live_stage == scene.caller


def _scene() -> bpy.types.Scene:
    # Looked up after each undo step: a datablock reference doesn't survive one.
    scene = bpy.context.scene
    assert scene is not None
    return scene
