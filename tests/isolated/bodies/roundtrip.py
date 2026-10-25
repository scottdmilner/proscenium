"""Isolated body: save/reopen through support.blend with load_post handlers, and the extension, registered.

Runs in a fresh Blender process (isolated/harness.py); see tests/isolated/test_roundtrip.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import bpy
from bpy.app.handlers import persistent
from pxr import Usd

import proscenium
from proscenium.api.bindings import BINDINGS
from support.blend import save_and_reopen


def save_and_reopen_with_handlers(path: str) -> dict[str, Any]:
    """Save and reopen a file holding one object; count persistent and transient load_post calls."""
    calls = {"persistent": 0, "transient": 0}

    @persistent
    def kept(*_args: object) -> None:
        calls["persistent"] += 1

    def dropped(*_args: object) -> None:
        calls["transient"] += 1

    scene = bpy.context.scene
    assert scene is not None
    scene.collection.objects.link(bpy.data.objects.new("Kept", None))
    bpy.app.handlers.load_post.extend([kept, dropped])
    proscenium.register()
    handle = BINDINGS.create_attached_binding(scene, "shot")
    caller = Usd.Stage.CreateInMemory()  # held across the reopen, so only the extension's handler can drop it
    BINDINGS.attach("shot", caller)
    attached_before = handle.synchronize(0).state.name
    save_and_reopen(Path(path))
    return {
        # The extension's load handler drops attachments (SRC-03), so the binding's source is unavailable.
        "synchronized": [attached_before, handle.synchronize(0).state.name],
        "objects": sorted(o.name for o in bpy.data.objects),
        "filepath": bpy.data.filepath,
        "load_post_calls": calls,
        "persistent_still_registered": kept in bpy.app.handlers.load_post,
        "transient_still_registered": dropped in bpy.app.handlers.load_post,
    }
