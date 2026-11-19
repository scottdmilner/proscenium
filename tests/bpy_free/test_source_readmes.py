"""Every directory of the extension's and the packages' sources has a README naming each entry (packages/AGENTS.md).

A README names an entry in backticks, a subdirectory with its trailing slash: `bindings.py`, `planner/`. The sources are
the extension's and each package's import directories, all through, and packages/ and each package's directory, whose
own entries are its pyproject.toml, src/, and any build hook.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import proscenium_cook
import proscenium_sync
import proscenium_ui

# The extension imports bpy, so it is found without importing it.
_EXTENSION_SPEC = importlib.util.find_spec("proscenium")
assert _EXTENSION_SPEC is not None and _EXTENSION_SPEC.origin is not None
EXTENSION = Path(_EXTENSION_SPEC.origin).parent
ROOT = EXTENSION.parents[1]
SOURCES = (EXTENSION, *(Path(package.__file__).parent for package in (proscenium_sync, proscenium_ui, proscenium_cook)))
PACKAGES = ROOT / "packages"
# Not sources: Python's caches, and the compiled modules the build puts in planner/ and tree_cook/, which their
# .gitignore files ignore.
SKIPPED = ("__pycache__", "_planner.*.so", "_planner.*.pyd", "_cook.*.so", "_cook.*.pyd")


def _directories() -> list[Path]:
    sources = [d for source in SOURCES for d in (source, *source.rglob("*")) if d.is_dir() and not _skipped(d)]
    packages = [PACKAGES, *(p for p in PACKAGES.iterdir() if p.is_dir() and not _skipped(p))]
    return sorted({*sources, *packages})


def _skipped(path: Path) -> bool:
    return any(path.match(pattern) or pattern in path.relative_to(ROOT).parts for pattern in SKIPPED)


@pytest.mark.parametrize("directory", _directories(), ids=lambda p: str(p.relative_to(ROOT)))
def test_readme_names_every_entry(directory: Path) -> None:
    readme = directory / "README.md"
    assert readme.is_file(), f"{directory.relative_to(ROOT)} has no README.md"
    text = readme.read_text(encoding="utf-8")
    entries = [p for p in directory.iterdir() if p.name != "README.md" and not _skipped(p)]
    unnamed = sorted(p.name for p in entries if f"`{p.name}{'/' if p.is_dir() else ''}`" not in text)
    assert unnamed == [], f"{readme.relative_to(ROOT)} doesn't name {unnamed}"
