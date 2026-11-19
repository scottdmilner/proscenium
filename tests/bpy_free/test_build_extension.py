"""tools/build_extension.py: the keys added to the staged manifest, and the cook's wheel."""

from __future__ import annotations

import hashlib
import json
import zipfile
from typing import TYPE_CHECKING

import pytest

from build_extension import BEGIN, END, _add_build_keys, build_wheel
from native_build import COOK, wheel_tag

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


def test_cook_wheel_ships_its_audited_module(tmp_path: Path) -> None:
    # Not a runtime dependency yet, so the extension's build doesn't make this wheel (docs/plans/cook-module.md).
    wheel = build_wheel("proscenium_cook", tmp_path)
    assert wheel.name.endswith(f"-{wheel_tag()}.whl")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        (module,) = [
            n for n in names if n.startswith("proscenium_cook/tree_cook/_cook.") and n.endswith((".so", ".pyd"))
        ]
        shipped = hashlib.sha256(archive.read(module)).hexdigest()
    # The build record names only a module that passed the linkage audit (native_build.sync_module).
    record = json.loads((COOK.out_dir / "build.json").read_text(encoding="utf-8"))
    assert shipped == record["module_sha256"]
    assert "proscenium_cook/node_definitions.usda" in names  # the cook loads its definitions at its first cook
    sources = (".cpp", ".h", "CMakeLists.txt", "README.md", "AGENTS.md", "CLAUDE.md", ".clang-format", ".gitignore")
    assert not [n for n in names if n.endswith(sources)]
