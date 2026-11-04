"""The extension's bpy-free parts import in a fresh interpreter with Blender modules blocked (AGENTS.md#layout)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from . import bpy_blocker

BLOCKER = Path(bpy_blocker.__file__)


def test_bpy_free_packages_import_without_bpy() -> None:
    # A fresh interpreter, so modules imported earlier in this run cannot hide an import of bpy.
    proc = subprocess.run(
        [
            sys.executable,
            str(BLOCKER),
            "proscenium",
            "proscenium.binding",
            "proscenium.binding.results",
            "--walk",
            "proscenium.core",
            "--walk",
            "proscenium.binding.source_access",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_blocker_rejects_bpy() -> None:
    # Guards the test above: it must be able to fail.
    proc = subprocess.run([sys.executable, str(BLOCKER), "bpy"], capture_output=True, text=True, check=False)
    assert proc.returncode != 0
    assert "Blender module" in proc.stderr
