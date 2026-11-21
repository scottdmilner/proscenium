"""tools/build/native_build.py: when a built module counts as current."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from native_build import NativeModule, _build_inputs, _current_module

if TYPE_CHECKING:
    from pathlib import Path

INPUTS = {"platform": "macos-arm64", "blender_tag": "v5.2.2", "sources_sha256": "abc"}


def _built(tmp_path: Path, record: dict[str, object] | None = None) -> tuple[NativeModule, Path]:
    """A module installed in its source directory, with a build record matching INPUTS and it unless given one."""
    module = NativeModule("_planner", tmp_path / "planner", tmp_path / "build")
    module.source_dir.mkdir()
    module.out_dir.mkdir()
    installed = module.source_dir / "_planner.cpython-313-darwin.so"
    installed.write_bytes(b"module")
    sha = hashlib.sha256(b"module").hexdigest()
    (module.out_dir / "build.json").write_text(
        json.dumps(record if record is not None else {**INPUTS, "module_sha256": sha})
    )
    return module, installed


def test_current_when_record_matches(tmp_path: Path) -> None:
    module, installed = _built(tmp_path)
    assert _current_module(module, INPUTS) == installed


@pytest.mark.parametrize("key", sorted(INPUTS))
def test_stale_when_an_input_changed(tmp_path: Path, key: str) -> None:
    module, _ = _built(tmp_path)
    assert _current_module(module, {**INPUTS, key: "changed"}) is None


def test_stale_when_module_changed_or_missing(tmp_path: Path) -> None:
    module, installed = _built(tmp_path)
    installed.write_bytes(b"another build")
    assert _current_module(module, INPUTS) is None
    installed.unlink()
    assert _current_module(module, INPUTS) is None


def test_stale_without_record(tmp_path: Path) -> None:
    module, _ = _built(tmp_path)
    (module.out_dir / "build.json").unlink()
    assert _current_module(module, INPUTS) is None


def test_sources_hash_covers_sources_only(tmp_path: Path) -> None:
    source_dir = tmp_path / "planner"
    source_dir.mkdir()
    (source_dir / "python_bindings.cpp").write_text("int a;")
    before = _build_inputs(source_dir)["sources_sha256"]
    (source_dir / "__init__.py").write_text("x = 1")
    assert _build_inputs(source_dir)["sources_sha256"] == before
    (source_dir / "python_bindings.cpp").write_text("int b;")
    assert _build_inputs(source_dir)["sources_sha256"] != before
