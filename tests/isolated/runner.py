"""Entry point of the fresh process started by isolated/harness.py (run_isolated); pytest never imports it.

    python runner.py <body.py> <function> <out.json> <kwargs json>                # bpy wheel
    blender -b --factory-startup --python runner.py -- <same arguments>           # binary
    blender --factory-startup --enable-event-simulate --python runner.py -- ...   # windowed binary

Resets Blender to the empty factory state (as the blender layer does), calls
the function, and writes {"value": ...} or {"error": traceback} to out.json.

In a window, the function is a generator instead, whose steps need the window's event loop between them: each
`yield` gives the seconds to wait before the next step, in which Blender handles the events the step simulated, and
its return value is the result. The window starts from --factory-startup's scene, which isn't emptied.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

TESTS = Path(__file__).resolve().parents[1]
# Blender's Python ignores PYTHONPATH, so put the support package, the extension
# source, and tools/ on sys.path here (harmless duplicates in the uv environment).
sys.path[:0] = [str(TESTS), str(TESTS.parent / "src"), str(TESTS.parent / "tools")]
WINDOW_START_SECONDS = 1.0  # before a windowed body's first step, so the window exists and has drawn


def main(argv: list[str]) -> int | None:
    """Run the body; returns the exit code, or None while a windowed body's steps still run."""
    body, function, out, kwargs = Path(argv[0]), argv[1], Path(argv[2]), json.loads(argv[3])
    try:
        import bpy

        if bpy.app.background:
            # Both runtimes otherwise start with the default Cube/Camera/Light scene.
            bpy.ops.wm.read_factory_settings(use_empty=True)
        else:
            # Opened with no file, the window shows the splash, which would take the cursor from what's under it.
            preferences: Any = bpy.context.preferences  # the stubs make it optional
            preferences.view.show_splash = False
        spec = importlib.util.spec_from_file_location(f"isolated_body_{body.stem}", body)
        assert spec is not None and spec.loader is not None, f"cannot load {body}"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        value = getattr(module, function)(**kwargs)
        if inspect.isgenerator(value):
            assert not bpy.app.background, f"{function} steps through a window, which background mode has none of"
            _run_steps(value, out)
            return None
        result = {"value": value}
    except Exception:  # noqa: BLE001 - reported to the pytest side
        result = {"error": traceback.format_exc()}
    out.write_text(json.dumps(result), encoding="utf-8")
    return 0


def _run_steps(steps: Generator[float, None, Any], out: Path) -> None:
    import bpy

    def run_next_step() -> float | None:
        try:
            return next(steps)
        except StopIteration as stopped:
            result = {"value": stopped.value}
        except Exception:  # noqa: BLE001 - reported to the pytest side
            result = {"error": traceback.format_exc()}
        out.write_text(json.dumps(result), encoding="utf-8")
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(run_next_step, first_interval=WINDOW_START_SECONDS)


if __name__ == "__main__":
    # The binary passes script arguments after "--"; a plain interpreter passes them directly.
    exit_code = main(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:])
    if exit_code is not None:  # a windowed body runs on in Blender's event loop, which quits once it's done
        sys.exit(exit_code)
