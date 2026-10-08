"""Save/reopen support for tests in the bpy wheel or the Blender binary."""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

if TYPE_CHECKING:
    from pathlib import Path


def save_and_reopen(path: Path) -> None:
    """Save the open file to `path` (normally under the test's tmp_path) and open it again.

    Every bpy reference held before the call is invalid afterwards; look
    datablocks up again by name. Handlers that are not @persistent are removed
    by the reopen, as with any file load.

    open_mainfile rebuilds all data from the file, even for the same path; only
    process-level state (Python, persistent handlers, add-ons, USD) carries over.
    """
    bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=str(path))
