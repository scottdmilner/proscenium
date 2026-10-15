"""Phase C correctness checks: each milestone case on its own scene, in a fresh wheel or Blender process.

Expected values come from how each scene is built or from USD (UsdGeom, UsdShade), never from Hydra.
A failing case is recorded and the remaining cases still run; the process fails if any case did.
"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# Run order; each name is a module in cases/.
CASES = [
    "subsets",
    "implicit",
    "instances",
    "edits",
    "untranslated",
    "large_arrays",
    "malformed",
    "bindings",
    "purposes",
    "primvars",
    "animation",
]


def run(module_dir: Path, only: list[str] | None = None) -> dict[str, Any]:
    import bpy

    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(module_dir))
    import apply
    from cases.harness import Case

    native = importlib.import_module("_hydra_bridge")
    results: dict[str, Any] = {}
    for name in only or CASES:
        with tempfile.TemporaryDirectory(prefix=f"hydra-case-{name}-") as tmp:
            case = Case(name, native, apply, Path(tmp))
            error = None
            try:
                module = importlib.import_module(f"cases.{name}")
                module.run(case)
            except Exception as exc:  # noqa: BLE001 - recorded per case; the process still fails
                error = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
        results[name] = {"checks": case.checks, "findings": case.findings, "error": error}
        status = "ok" if error is None else f"FAILED ({error})"
        print(f"{name}: {len(case.checks)} checks, {status}")
    return {"blender": bpy.app.version_string, "cases": results}


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    result = run(Path(args[0]), args[2:] or None)
    Path(args[1]).write_text(json.dumps(result, indent=2, default=str) + "\n")
    failed = [name for name, case in result["cases"].items() if case["error"]]
    total = sum(len(case["checks"]) for case in result["cases"].values())
    print(f"Hydra correctness: {total} checks passed" + (f"; failed cases: {', '.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)
