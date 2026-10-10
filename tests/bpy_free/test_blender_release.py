"""The targeted Blender release comes from uv.lock's bpy version."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import blender_release

ROOT = Path(__file__).parents[2]


def test_release_is_the_locked_bpy_version() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    (bpy,) = [p for p in lock["package"] if p["name"] == "bpy"]
    assert blender_release.blender_version() == bpy["version"]
    assert blender_release.blender_tag() == f"v{bpy['version']}"


def test_lock_without_one_bpy_version_fails(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text('version = 1\n\n[[package]]\nname = "numpy"\nversion = "2.3.0"\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="Expected one locked bpy version"):
        blender_release.blender_version(lock)
