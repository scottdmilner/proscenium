"""Isolated layer: each test runs its body in a fresh Blender process (isolated/harness.py).

Use it for what a reused process cannot do cleanly: real file loads with
handlers, extension installation, or anything that leaves process-wide state.

Fixtures:
- `wheel`: a fresh bpy-wheel process. The default for isolated tests.
- `binary`: the Blender binary alone, for what the wheel already shows in another layer.
- `runtime`: parametrized over the wheel and the Blender binary, for smoke tests
  that should also pass in the runtime users run.
- `hydra_bridge`: the directory of M1b's compiled Hydra bridge, which M4's prototypes run. Built from its
  sources once per run, unless PROSCENIUM_HYDRA_BRIDGE names a directory holding a prebuilt one (CI on Linux).
Without a binary, binary runs are skipped, unless PROSCENIUM_REQUIRE_BLENDER is set (CI).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from filelock import FileLock

from blender_paths import find_blender

from .harness import WHEEL, Runtime, RuntimeKind

ROOT = Path(__file__).resolve().parents[2]
BRIDGE_BUILD = ROOT / "tools/feasibility/hydra_bridge/build.py"
BRIDGE_OUT = ROOT / "build/hydra-bridge"  # build.py's default, which run.py and the measurements also use


@pytest.fixture
def wheel() -> Runtime:
    return WHEEL


@pytest.fixture
def binary() -> Runtime:
    return _binary()


@pytest.fixture(params=list(RuntimeKind))
def runtime(request: pytest.FixtureRequest) -> Runtime:
    return WHEEL if request.param is RuntimeKind.WHEEL else _binary()


def _binary() -> Runtime:
    blender = find_blender()
    if blender is None:
        message = "Blender binary not found; set BLENDER"
        if os.environ.get("PROSCENIUM_REQUIRE_BLENDER"):
            pytest.fail(message)
        pytest.skip(message)
    return Runtime(RuntimeKind.BINARY, blender)


@pytest.fixture(scope="session")
def hydra_bridge(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The bridge built from its current sources, once per run: an incremental build when nothing changed."""
    prebuilt = os.environ.get("PROSCENIUM_HYDRA_BRIDGE")
    if prebuilt:
        if not any(Path(prebuilt).glob("_hydra_bridge.*")):
            pytest.fail(f"PROSCENIUM_HYDRA_BRIDGE names {prebuilt}, which holds no built bridge")
        return Path(prebuilt).resolve()
    if "PYTEST_XDIST_WORKER" not in os.environ:
        _build_bridge()
        return BRIDGE_OUT
    # Parallel workers share the run's base temp directory: the first to take the lock builds, and the rest wait.
    shared = tmp_path_factory.getbasetemp().parent
    with FileLock(shared / "hydra-bridge.lock"):
        built = shared / "hydra-bridge.built"
        if not built.exists():
            _build_bridge()
            built.touch()
    return BRIDGE_OUT


def _build_bridge() -> None:
    result = subprocess.run(
        [sys.executable, str(BRIDGE_BUILD), "--out", str(BRIDGE_OUT)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"building the Hydra bridge failed:\n{(result.stdout + result.stderr)[-4000:]}")
