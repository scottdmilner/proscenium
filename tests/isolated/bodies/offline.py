"""Isolated bodies: F-OFFLINE's saved display, published with the extension and opened without it (SCHEMA-05).

Each runs in a fresh process (isolated/harness.py); see tests/isolated/test_offline.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import bpy

from support.blend import collection_content


def publish_and_save(tmp_dir: str, path: str) -> dict[str, Any]:
    """With the extension registered from source: a binding on F-OFFLINE, its display published by hand, saved."""
    import proscenium
    from fixtures import source_access
    from proscenium.synchronization import Synchronization
    from support.display import publish_by_hand

    proscenium.register()
    with source_access.offline(Path(tmp_dir)) as scene:
        handle = Synchronization().create_file_binding(bpy.data.scenes["Scene"], scene.root, name="Shot")
        destination = bpy.data.collections["Shot"]
        publish_by_hand(handle.binding_id, destination, scene.display)
        bpy.ops.wm.save_as_mainfile(filepath=path, check_existing=False)
        return collection_content(destination)


def open_without_extension(path: str) -> dict[str, Any]:
    """Open the saved file in a process that never imports the extension. An error report raises RuntimeError."""
    loaded = bpy.ops.wm.open_mainfile(filepath=path)
    return {
        "loaded": sorted(loaded),
        "extension_imported": "proscenium" in sys.modules,
        "content": collection_content(bpy.data.collections["Shot"]),
    }
