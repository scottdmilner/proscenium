"""The packages' bpy-free parts import in a fresh interpreter with Blender modules blocked (packages/README.md)."""

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
            "proscenium_sync",
            "proscenium_sync.results",
            "proscenium_ui",
            "proscenium_ui.scene_graph_widget",
            "proscenium_ui.property_viewer_widget",
            "--walk",
            "proscenium_ui.widget_model",
            "--walk",
            "proscenium_ui.scene_graph_widget.prim_tree",
            "--walk",
            "proscenium_ui.property_viewer_widget.property_list",
            "--walk",
            "proscenium_sync.planner",
            "--walk",
            "proscenium_sync.source_access",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_sync_api_loads_nothing_for_a_unit_or_a_dunder() -> None:
    # proscenium_sync's __getattr__ loads the API, which imports bpy, for any name but these: a from-import of a unit,
    # which tries the unit as an attribute first, and a dunder a tool probes for.
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(BLOCKER.parent)!r})\n"
        "import bpy_blocker\n"
        "bpy_blocker.import_without_blender(['proscenium_sync'])\n"
        "import proscenium_sync\n"
        "from proscenium_sync import planner\n"
        "assert getattr(proscenium_sync, '__wrapped__', None) is None\n"
        "assert 'proscenium_sync.bindings' not in sys.modules\n"
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def test_blocker_rejects_bpy() -> None:
    # Guards the test above: it must be able to fail.
    proc = subprocess.run([sys.executable, str(BLOCKER), "bpy"], capture_output=True, text=True, check=False)
    assert proc.returncode != 0
    assert "Blender module" in proc.stderr
