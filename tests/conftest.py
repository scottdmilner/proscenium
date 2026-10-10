"""Configuration shared by every test layer.

- Each test gets the marker of the directory it lives in (bpy_free, blender, or
  isolated), so `pytest -m bpy_free` selects tests/bpy_free/ without per-test markers.
- Tests marked `alab` are skipped unless PROSCENIUM_ALAB_ROOT is set, in the
  environment or in the repository's .env (see .env.example).
- Blender (the bpy wheel and binary subprocesses) uses a throwaway user
  config dir instead of the developer's real one.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest
from dotenv import load_dotenv

TESTS = Path(__file__).parent
LAYERS = ("bpy_free", "blender", "isolated")

# Local settings such as PROSCENIUM_ALAB_ROOT; variables already set in the environment win.
load_dotenv(TESTS.parent / ".env")

# Blender reads BLENDER_USER_RESOURCES when bpy is imported, and subprocesses
# inherit it. Setting it here, while pytest loads this file, happens before any
# test module imports bpy.
_USER_RESOURCES = tempfile.mkdtemp(prefix="proscenium-test-user-")
os.environ["BLENDER_USER_RESOURCES"] = _USER_RESOURCES


def pytest_unconfigure(config: pytest.Config) -> None:
    """At the end of the run, delete the throwaway Blender user dir."""
    shutil.rmtree(_USER_RESOURCES, ignore_errors=True)


# tryfirst: the markers must be added before pytest's -m option filters on them.
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """After collection, mark each test with its layer and skip ALab tests without ALab."""
    for item in items:
        layer = item.path.relative_to(TESTS).parts[0]  # tests/<layer>/...
        if layer not in LAYERS:
            raise pytest.UsageError(f"{item.nodeid}: put tests under tests/bpy_free, tests/blender, or tests/isolated")
        item.add_marker(layer)
        if item.get_closest_marker("alab") and not os.environ.get("PROSCENIUM_ALAB_ROOT"):
            item.add_marker(pytest.mark.skip(reason="set PROSCENIUM_ALAB_ROOT to run ALab tests"))
