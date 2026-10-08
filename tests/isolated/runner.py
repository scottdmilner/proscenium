"""Entry point of the fresh process started by isolated/harness.py (run_isolated); pytest never imports it.

    python runner.py <body.py> <function> <out.json> <kwargs json>                # bpy wheel
    blender -b --factory-startup --python runner.py -- <same arguments>           # binary

Resets Blender to the empty factory state (as the blender layer does), calls
the function, and writes {"value": ...} or {"error": traceback} to out.json.
"""

import importlib.util
import json
import sys
import traceback
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
# Blender's Python ignores PYTHONPATH, so put the support package, the extension
# source, and tools/ on sys.path here (harmless duplicates in the uv environment).
sys.path[:0] = [str(TESTS), str(TESTS.parent / "src"), str(TESTS.parent / "tools")]


def main(argv: list[str]) -> int:
    body, function, out, kwargs = Path(argv[0]), argv[1], Path(argv[2]), json.loads(argv[3])
    try:
        import bpy

        # Both runtimes otherwise start with the default Cube/Camera/Light scene.
        bpy.ops.wm.read_factory_settings(use_empty=True)
        spec = importlib.util.spec_from_file_location(f"isolated_body_{body.stem}", body)
        assert spec is not None and spec.loader is not None, f"cannot load {body}"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = {"value": getattr(module, function)(**kwargs)}
    except Exception:  # noqa: BLE001 - reported to the pytest side
        result = {"error": traceback.format_exc()}
    out.write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    # The binary passes script arguments after "--"; a plain interpreter passes them directly.
    sys.exit(main(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]))
