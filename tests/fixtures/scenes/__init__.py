"""Index of the static scenes in this directory, and the only way to use them: copy_scene.

Scenes are never opened in place. Copying one into the test's tmp_path first
means no test can save or reload a repository file, and parallel tests never
touch the same file. tests/bpy_free/test_fixture_registry.py checks that this
index matches the directories here.
"""

from __future__ import annotations

import shutil
from enum import Enum
from pathlib import Path

SCENES = Path(__file__).parent


class Scene(Enum):
    """A static scene directory; each holds .usda layers with a comment on their purpose."""

    SOURCE_ACCESS = "source_access"  # layers for F-DIRTY-LAYER, F-PRIVATE-STAGE, F-CACHED-STAGE
    PRODUCTION_LIKE = "production_like"  # assets/ for the generated CI fixture

    @property
    def path(self) -> Path:
        return SCENES / self.value


def copy_scene(src: Scene, dest: Path) -> Path:
    """Copy the files of `src` into `dest` (normally the test's tmp_path) and return `dest`."""
    shutil.copytree(src.path, dest, dirs_exist_ok=True)
    return dest
