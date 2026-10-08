"""Run a function in a fresh Blender process and return its result, for tests/isolated/.

A body is a plain function in a module under tests/isolated/bodies/. It runs in
the fresh process (no pytest there), takes JSON-compatible keyword arguments,
and returns a JSON-compatible value; the test asserts on that value.

    result = run_isolated(runtime, BODIES / "roundtrip.py", "save_and_reopen", tmp_path, name="Kept")

Two runtimes, chosen by the `runtime` fixtures in tests/isolated/conftest.py:
- wheel: a new uv-environment Python process that imports the bpy wheel (~0.85 s).
- binary: the Blender executable in background mode (~1.2 s), what users run.

Each call gets its own Blender user dir under tmp_path, so parallel workers
never share Blender configuration.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

RUNNER = Path(__file__).with_name("runner.py")


class RuntimeKind(StrEnum):
    WHEEL = "wheel"  # a fresh uv-environment Python process importing the bpy wheel
    BINARY = "binary"  # the Blender executable in background mode


@dataclass(frozen=True)
class Runtime:
    kind: RuntimeKind
    blender: str | None = None  # the executable; set exactly for RuntimeKind.BINARY

    def __post_init__(self) -> None:
        if (self.kind is RuntimeKind.BINARY) != (self.blender is not None):
            raise ValueError(f"the Blender executable is required for, and only for, the binary runtime: {self}")

    def command(self, *args: str) -> list[str]:
        """Command line that runs runner.py with `args`."""
        if self.blender is None:
            return [sys.executable, str(RUNNER), *args]
        return [
            self.blender,
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(RUNNER),
            "--",
            *args,
        ]


WHEEL = Runtime(RuntimeKind.WHEEL)


def run_isolated(
    runtime: Runtime, body: Path, function: str, tmp_path: Path, timeout: float = 300, **kwargs: Any
) -> Any:
    """Call `function(**kwargs)` from `body` in a fresh `runtime` process and return its value.

    Fails the test with the process output if the body raises or the process
    exits without writing a result.
    """
    run_dir = tmp_path / f"isolated-{runtime.kind}-{function}"
    run_dir.mkdir()
    out = run_dir / "result.json"
    env = {**os.environ, "BLENDER_USER_RESOURCES": str(run_dir / "blender-user")}
    cmd = runtime.command(str(body), function, str(out), json.dumps(kwargs))
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout, check=False)
    if not out.exists():
        log = (proc.stdout + proc.stderr)[-4000:]
        raise AssertionError(f"{runtime.kind} process exited with {proc.returncode} without a result:\n{log}")
    result = json.loads(out.read_text(encoding="utf-8"))
    if "error" in result:
        raise AssertionError(f"{body.name}:{function} raised in the {runtime.kind} process:\n{result['error']}")
    return result["value"]
