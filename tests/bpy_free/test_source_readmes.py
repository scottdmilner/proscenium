"""Every directory of the extension's and the packages' sources has a README naming each entry (AGENTS.md#layout).

A README names an entry in backticks, a subdirectory with its trailing slash: `bindings.py`, `planner/`. The sources are
the extension's and each package's import directories, all through, and packages/ and each package's directory, whose
own entries are its pyproject.toml, src/, and any build hook.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import proscenium
import proscenium_sync
import proscenium_ui

ROOT = Path(proscenium.__file__).parents[2]
SOURCES = tuple(Path(package.__file__).parent for package in (proscenium, proscenium_sync, proscenium_ui))
PACKAGES = ROOT / "packages"
# Not sources: Python's caches, and the compiled module the build puts in planner/, which planner/.gitignore ignores.
SKIPPED = ("__pycache__", "_planner.*.so", "_planner.*.pyd")


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
