"""When a windowed test runs: in CI always, and locally only once what it covers has changed since it last passed.

A windowed test's Blender window takes over the screen, so a local run skips it while the files it covers hash to
what they did when it last passed, as pytest's cache records. Its module names those files in its `windowed` marker
(`pytestmark = pytest.mark.windowed(covers=(...))`, paths from the repository root, a directory for every file under
it); the test's own module and the isolated layer's harness count too. It runs anyway when `CI` is set (GitHub
Actions sets it), when `PROSCENIUM_RUN_WINDOWED` is set, or when the command line names its module.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ISOLATED = Path(__file__).parent
# What every windowed test runs through, so a change to any of it runs them all again.
HARNESS_FILES = (ISOLATED / "conftest.py", ISOLATED / "harness.py", ISOLATED / "runner.py", Path(__file__))
COVERED_DIGEST = pytest.StashKey[str]()  # on a test's item, from its fixture to its report


def covered_files_digest(item: pytest.Item, blender_executable: str) -> str:
    """A hash of the Blender executable's path and the contents of every file the test covers."""
    marker = item.get_closest_marker("windowed")
    if marker is None or not marker.kwargs.get("covers"):
        pytest.fail(f"{item.nodeid}: a windowed test's module names what it covers: pytest.mark.windowed(covers=...)")
    covered_paths = [item.path, *HARNESS_FILES, *(ROOT / covered for covered in marker.kwargs["covers"])]
    digest = hashlib.sha256(blender_executable.encode())
    for file_path in sorted(_covered_files(item, covered_paths)):
        digest.update(file_path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(file_path.read_bytes() + b"\0")
    return digest.hexdigest()


def is_run_regardless(item: pytest.Item) -> bool:
    """Whether the test runs even though nothing it covers changed: in CI, when asked to, or when named."""
    if os.environ.get("CI") or os.environ.get("PROSCENIUM_RUN_WINDOWED"):
        return True
    invocation_dir = item.config.invocation_params.dir
    return any((invocation_dir / argument.split("::")[0]).resolve() == item.path for argument in item.config.args)


def passed_digest(item: pytest.Item) -> str | None:
    """The covered files' digest when the test last passed, or None if it hasn't passed with pytest's cache on."""
    cache = getattr(item.config, "cache", None)
    return None if cache is None else cache.get(_cache_key(item), None)


def record_pass(item: pytest.Item) -> None:
    """Record the covered files' digest the test just passed with."""
    cache = getattr(item.config, "cache", None)
    digest = item.stash.get(COVERED_DIGEST, None)
    if cache is not None and digest is not None:
        cache.set(_cache_key(item), digest)


def _cache_key(item: pytest.Item) -> str:
    # One key per test, so parallel workers never write the same one; hashed, since a node ID's colons can't name a
    # file on Windows.
    return f"proscenium/windowed-passed/{hashlib.sha256(item.nodeid.encode()).hexdigest()[:16]}"


def _covered_files(item: pytest.Item, covered_paths: list[Path]) -> set[Path]:
    files: set[Path] = set()
    for covered_path in covered_paths:
        if covered_path.is_dir():
            files.update(path for path in covered_path.rglob("*") if path.is_file() and not _is_incidental(path))
        elif covered_path.is_file():
            files.add(covered_path)
        else:  # a covered file renamed or removed would otherwise never run the test again
            pytest.fail(f"{item.nodeid}: its windowed marker covers {covered_path.relative_to(ROOT)}, which is missing")
    return files


def _is_incidental(path: Path) -> bool:
    # Bytecode, and files such as Finder's .DS_Store, which change without what the test covers changing.
    return "__pycache__" in path.parts or path.name.startswith(".")
