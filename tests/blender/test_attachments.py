"""Undo neither restores nor removes attachments of callers' stages (UNDO-06).

The attachment is runtime state keyed by binding identity; the binding's records are Blender data
that undo changes. Here undo and redo change a binding's requested settings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
from pxr import Usd

from fixtures import source_access
from support import undo

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.synchronization import Synchronization


def test_undo_and_redo_leave_attachments(sync: Synchronization, tmp_path: Path) -> None:
    undo.require_global_undo()
    handle = sync.create_attached_binding(bpy.data.scenes[0], "shot")
    with source_access.reattach(tmp_path) as scene:
        sync.attach("shot", scene.caller)
        undo.push("base")
        handle.set_settings(payload_policy=Usd.Stage.LoadNone)
        undo.push("change")
        undo.undo()
        assert handle.requested_settings().payload_policy == Usd.Stage.LoadAll  # undone
        assert handle.live_stage() == scene.caller  # found by binding identity
        undo.redo()
        assert handle.requested_settings().payload_policy == Usd.Stage.LoadNone
        assert handle.live_stage() == scene.caller
