"""tools/build_extension.py: the keys added to the staged manifest."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from build_extension import BEGIN, END, _add_build_keys

if TYPE_CHECKING:
    from pathlib import Path


def test_build_keys_added_inside_generated_block(tmp_path: Path) -> None:
    manifest = tmp_path / "blender_manifest.toml"
    manifest.write_text(f'blender_version_min = "5.2.0"\n{BEGIN}wheels = []\n{END}\n[build]\n')
    _add_build_keys(manifest, "linux-x64", "5.2.2")
    keys = 'platforms = ["linux-x64"]\nblender_version_max = "5.3.0"\n'
    assert manifest.read_text() == f'blender_version_min = "5.2.0"\n{BEGIN}wheels = []\n{keys}{END}\n[build]\n'


def test_minimum_outside_locked_minor_fails(tmp_path: Path) -> None:
    manifest = tmp_path / "blender_manifest.toml"
    manifest.write_text(f'blender_version_min = "5.1.0"\n{BEGIN}{END}\n[build]\n')
    with pytest.raises(SystemExit, match="5.2.x"):
        _add_build_keys(manifest, "linux-x64", "5.2.2")
