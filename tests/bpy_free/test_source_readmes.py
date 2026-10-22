"""Every directory of the extension source has a README naming each of its files and subdirectories (AGENTS.md#layout).

A README names an entry in backticks, a subdirectory with its trailing slash: `bindings.py`, `core/`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import proscenium

SOURCE = Path(proscenium.__file__).parent
# Not sources: Python's caches, and the compiled module the build puts in core/, which core/.gitignore ignores.
SKIPPED = ("__pycache__", "_core.*.so", "_core.*.pyd")


def _directories() -> list[Path]:
    return [SOURCE, *sorted(p for p in SOURCE.rglob("*") if p.is_dir() and not _skipped(p))]


def _skipped(path: Path) -> bool:
    return any(path.match(pattern) or pattern in path.relative_to(SOURCE).parts for pattern in SKIPPED)


@pytest.mark.parametrize("directory", _directories(), ids=lambda p: str(p.relative_to(SOURCE.parent)))
def test_readme_names_every_entry(directory: Path) -> None:
    readme = directory / "README.md"
    assert readme.is_file(), f"{directory.relative_to(SOURCE.parent)} has no README.md"
    text = readme.read_text(encoding="utf-8")
    entries = [p for p in directory.iterdir() if p.name != "README.md" and not _skipped(p)]
    unnamed = sorted(p.name for p in entries if f"`{p.name}{'/' if p.is_dir() else ''}`" not in text)
    assert unnamed == [], f"{readme.relative_to(SOURCE.parent)} doesn't name {unnamed}"
