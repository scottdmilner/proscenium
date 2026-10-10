"""Isolated layer: each test runs its body in a fresh Blender process (isolated/harness.py).

Use it for what a reused process cannot do cleanly: real file loads with
handlers, extension installation, or anything that leaves process-wide state.

Fixtures:
- `wheel`: a fresh bpy-wheel process. The default for isolated tests.
- `runtime`: parametrized over the wheel and the Blender binary, for smoke tests
  that should also pass in the runtime users run. The binary case is skipped
  when no binary is found, unless PROSCENIUM_REQUIRE_BLENDER is set (CI).
"""

from __future__ import annotations

import os

import pytest

from blender_paths import find_blender

from .harness import WHEEL, Runtime, RuntimeKind


@pytest.fixture
def wheel() -> Runtime:
    return WHEEL


@pytest.fixture(params=list(RuntimeKind))
def runtime(request: pytest.FixtureRequest) -> Runtime:
    if request.param is RuntimeKind.WHEEL:
        return WHEEL
    blender = find_blender()
    if blender is None:
        message = "Blender binary not found; set BLENDER"
        if os.environ.get("PROSCENIUM_REQUIRE_BLENDER"):
            pytest.fail(message)
        pytest.skip(message)
    return Runtime(RuntimeKind.BINARY, blender)
