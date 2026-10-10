"""The extension's bpy-free parts import with Blender modules blocked (AGENTS.md#layout)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from . import bpy_blocker

BLOCKER = Path(bpy_blocker.__file__)


def test_proscenium_and_core_import_without_bpy() -> None:
    # A fresh interpreter, so modules imported earlier in this run cannot hide an import of bpy.
    proc = subprocess.run(
        [sys.executable, str(BLOCKER), "proscenium", "--walk", "proscenium.core"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_blocker_rejects_bpy() -> None:
    # Guards the test above: it must be able to fail.
    with pytest.raises(ImportError, match="Blender module"):
        bpy_blocker.import_without_blender(["bpy"])


def test_layer_runs_with_blender_blocked() -> None:
    with pytest.raises(ImportError, match="Blender module"):
        import bpy  # noqa: F401
