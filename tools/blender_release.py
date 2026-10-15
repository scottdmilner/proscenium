"""The Blender release this project targets: the bpy version locked in uv.lock.

The lock is the single source: CI downloads that Blender binary (.github/actions/setup-blender),
and the Hydra bridge builds against that release's pinned dependencies. Reads the lock rather
than the installed wheel, so it works before `uv sync` and in isolated build environments.

Usage: python tools/blender_release.py [--tag]
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

LOCK = Path(__file__).resolve().parents[1] / "uv.lock"


def blender_version(lock: Path = LOCK) -> str:
    """The locked bpy version, e.g. '5.2.2'; bpy wheels share Blender's release version."""
    packages = tomllib.loads(lock.read_text(encoding="utf-8")).get("package", [])
    versions = {p["version"] for p in packages if p.get("name") == "bpy"}
    if len(versions) != 1:
        raise RuntimeError(f"Expected one locked bpy version in {lock}, found {sorted(versions)}")
    return versions.pop()


def blender_tag(lock: Path = LOCK) -> str:
    """The Blender git tag of the locked release, e.g. 'v5.2.2'."""
    return f"v{blender_version(lock)}"


if __name__ == "__main__":
    print(blender_tag() if "--tag" in sys.argv[1:] else blender_version())
