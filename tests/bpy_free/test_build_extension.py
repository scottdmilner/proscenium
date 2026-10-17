"""tools/build_extension.py: when a built core counts as current, and the keys added to the staged manifest."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from build_extension import BEGIN, END, _add_build_keys, _core_inputs, _current_core

if TYPE_CHECKING:
    from pathlib import Path

INPUTS = {"platform": "macos-arm64", "blender_tag": "v5.2.2", "sources_sha256": "abc"}


def _core(tmp_path: Path, record: dict[str, object] | None = None) -> tuple[Path, Path, Path]:
    core_dir = tmp_path / "core"
    core_dir.mkdir()
    module = core_dir / "_core.cpython-313-darwin.so"
    module.write_bytes(b"module")
    path = tmp_path / "build.json"
    sha = hashlib.sha256(b"module").hexdigest()
    path.write_text(json.dumps(record if record is not None else {**INPUTS, "module_sha256": sha}))
    return core_dir, path, module


def test_current_when_record_matches(tmp_path: Path) -> None:
    core_dir, record, module = _core(tmp_path)
    assert _current_core(core_dir, record, INPUTS) == module


@pytest.mark.parametrize("key", sorted(INPUTS))
def test_stale_when_an_input_changed(tmp_path: Path, key: str) -> None:
    core_dir, record, _ = _core(tmp_path)
    assert _current_core(core_dir, record, {**INPUTS, key: "changed"}) is None


def test_stale_when_module_changed_or_missing(tmp_path: Path) -> None:
    core_dir, record, module = _core(tmp_path)
    module.write_bytes(b"another build")
    assert _current_core(core_dir, record, INPUTS) is None
    module.unlink()
    assert _current_core(core_dir, record, INPUTS) is None


def test_stale_without_record(tmp_path: Path) -> None:
    core_dir, record, _ = _core(tmp_path)
    record.unlink()
    assert _current_core(core_dir, record, INPUTS) is None


def test_sources_hash_covers_sources_only(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir()
    (core_dir / "module.cpp").write_text("int a;")
    before = _core_inputs(core_dir)["sources_sha256"]
    (core_dir / "__init__.py").write_text("x = 1")
    assert _core_inputs(core_dir)["sources_sha256"] == before
    (core_dir / "module.cpp").write_text("int b;")
    assert _core_inputs(core_dir)["sources_sha256"] != before


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
