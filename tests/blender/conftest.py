"""Blender layer: tests share their worker's process running the bpy wheel, with explicit reset.

Every test starts from Blender's empty factory state, checked against a clean
baseline, and whatever it registered is removed afterwards. Tests that need a
fresh process belong in tests/isolated/.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import proscenium

from . import state as blender_state

if TYPE_CHECKING:
    from collections import Counter
    from collections.abc import Generator
    from types import ModuleType


@pytest.fixture(scope="session")
def baseline_handlers() -> dict[str, Counter[str]]:
    """The handlers Blender itself registers after a factory reset, once per worker."""
    blender_state.reset()
    return blender_state.handler_names(blender_state.snapshot_handlers())


@pytest.fixture(autouse=True)
def clean_blender(baseline_handlers: dict[str, Counter[str]]) -> Generator[None]:
    """Start each test from a verified clean state; remove what it registered afterwards."""
    blender_state.reset()
    problems = blender_state.baseline_problems(baseline_handlers)
    assert not problems, "Blender state is not clean before the test:\n" + "\n".join(problems)
    before = blender_state.snapshot_handlers()
    yield
    blender_state.cleanup(before)


@pytest.fixture
def extension() -> Generator[ModuleType]:
    """The extension registered in-process from the source tree (not installed)."""
    proscenium.register()
    yield proscenium
    # clean_blender's cleanup unregisters it if the test did not.
