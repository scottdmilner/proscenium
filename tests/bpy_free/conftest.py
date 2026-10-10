"""bpy_free layer: tests that run without Blender. Importing a Blender module here is an error.

The third-party packages bundled in the bpy wheel's site-packages (e.g. pxr,
MaterialX) are allowed: they are importable without bpy through
tools/bpy-site-packages.

Imports happen at two different times, so Blender modules are blocked in two hooks:
- Collection: pytest imports each test file before any test runs, so a
  module-level `import bpy` executes then. pytest_make_collect_report covers it;
  the file fails with a collection error.
- Running: imports inside test functions and fixtures execute when the test
  runs. pytest_runtest_protocol covers those.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .bpy_blocker import blender_modules_blocked

if TYPE_CHECKING:
    from collections.abc import Generator

LAYER = Path(__file__).parent


def _in_layer(path: Path) -> bool:
    # Some hooks (pytest_runtest_protocol) run for every test in the session, wherever
    # their conftest lives, so each hook checks the path itself.
    return path.is_relative_to(LAYER)


# wrapper=True: the code before `yield` runs before pytest's own hook, the code after it once that hook returns.
@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector: pytest.Collector) -> Generator[None, object, object]:
    """Block Blender modules while pytest imports a test file in this layer (catches module-level imports)."""
    if not (isinstance(collector, pytest.Module) and _in_layer(collector.path)):
        return (yield)
    with blender_modules_blocked():
        return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, object, object]:
    """Block Blender modules while a test in this layer runs, including its fixtures (catches imports inside them)."""
    if not _in_layer(item.path):
        return (yield)
    with blender_modules_blocked():
        return (yield)
