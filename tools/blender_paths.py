"""Locate the Blender binary and the extension CLI shipped inside the bpy wheel."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
from pathlib import Path

DEFAULT_BLENDER = {
    "Darwin": ["/Applications/Blender.app/Contents/MacOS/Blender"],
    "Linux": ["blender"],
    "Windows": [r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe", "blender.exe"],
}


def find_blender() -> str | None:
    """The BLENDER env var, else a platform default; None if neither exists."""
    for candidate in [os.environ.get("BLENDER"), *DEFAULT_BLENDER.get(platform.system(), [])]:
        if candidate and (shutil.which(candidate) or Path(candidate).exists()):
            return shutil.which(candidate) or candidate
    return None


def wheel_extension_cli() -> Path | None:
    """blender_ext.py from the bpy wheel, found without importing bpy.

    It only needs the standard library, so any Python 3.13 can run it
    (see docs/feasibility/runtime-record.md#packaging).
    """
    spec = importlib.util.find_spec("bpy")
    if spec is None or spec.origin is None:
        return None
    matches = sorted(Path(spec.origin).parent.glob("*/scripts/addons_core/bl_pkg/cli/blender_ext.py"))
    return matches[-1] if matches else None
