"""M4 B6: what replacing one unit of ALab's display costs in the object baseline, against a full synchronization.

    uv run python tools/feasibility/hydra_bridge/measure/updates.py [--repeats 3] [--out build/hydra-bridge/updates]

Runs in the bpy wheel, in one process, timing each step with a monotonic clock. A full synchronization
(capture, planning, construction, depsgraph evaluation) comes first. Then one real edit: a translation of one
object outside instances, followed by an incremental capture, planning, and the object's replacement. Then each
of update.py's sample units is replaced from the unchanged plan, under both user policies where they differ:
prepare, publish, retire, and the depsgraph evaluation after it. Writes <out>/updates.json.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(HERE), str(HERE.parent)]

import alab_entry  # noqa: E402
import bpy  # noqa: E402
from pxr import Gf, Usd, UsdGeom  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable

ALAB_TIME = 1004.0  # the first of ALab's time codes, as run.py measures


def timed[T](steps: dict[str, float], name: str, call: Callable[[], T]) -> T:
    start = time.perf_counter()
    result = call()
    steps[name] = time.perf_counter() - start
    return result


def evaluate() -> None:
    view_layer: Any = bpy.context.view_layer  # never None in a running Blender
    view_layer.update()


def replacement(update: Any, plan: Any, display: Any, collection: Any, unit: Any, users: Any) -> tuple[Any, dict]:
    """Replace `unit`, returning the published display and each step's time and what it changed."""
    steps: dict[str, float] = {}
    prepared = timed(steps, "prepare", lambda: update.prepare(plan, display, unit, users))
    published = timed(steps, "publish", lambda: update.publish(prepared, display, collection))
    retired = len(prepared.retired)
    kept = timed(steps, "retire", lambda: update.retire(prepared))
    timed(steps, "evaluate", evaluate)
    steps["total"] = sum(steps.values())
    changed = {
        "objects replaced": len(prepared.objects),
        "objects repointed": len(prepared.repointed),
        "meshes replaced": len(unit.meshes),
        "materials replaced": len(unit.materials),
        "retired": retired,
        "kept for other users": len(kept),
    }
    return published, {"steps": steps, "changed": changed}


def median_steps(runs: list[dict]) -> dict[str, float]:
    return {step: statistics.median(run["steps"][step] for run in runs) for step in runs[0]["steps"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, default=ROOT / "build/hydra-bridge/updates")
    parser.add_argument("--module-dir", type=Path, default=ROOT / "build/hydra-bridge")
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    alab = os.environ.get("PROSCENIUM_ALAB_ROOT")
    if not alab:
        raise SystemExit("needs PROSCENIUM_ALAB_ROOT (environment or .env)")
    out: Path = args.out.resolve()
    entry = out / "scenes" / "alab_entry_measure.usda"
    entry.unlink(missing_ok=True)
    alab_entry.write(Path(alab) / "entry.usda", entry)

    sys.path.insert(0, str(args.module_dir))
    import _hydra_bridge as native  # ty: ignore[unresolved-import] - built into build/hydra-bridge
    import apply
    import update

    full: dict[str, float] = {}
    stage = timed(full, "stage open", lambda: Usd.Stage.Open(str(entry), Usd.Stage.LoadAll))
    bridge = timed(full, "bridge construction", lambda: native.Bridge(stage))
    snapshot = timed(full, "capture", lambda: bridge.capture(ALAB_TIME))
    plan = timed(full, "planning", lambda: native.build_plan(snapshot))
    collection = bpy.data.collections.new("Prototype")
    blender_scene: Any = bpy.context.scene  # never None in a running Blender
    blender_scene.collection.children.link(collection)
    display = timed(full, "construction", lambda: apply.apply(plan, collection))
    timed(full, "evaluate", evaluate)
    records = plan.objects  # each read converts every record
    full["synchronization"] = sum(full[s] for s in ("capture", "planning", "construction", "evaluate"))
    results: dict[str, Any] = {
        "scene": str(entry),
        "runtime": f"bpy wheel {bpy.app.version_string}, in-process",
        "repeats": args.repeats,
        "plan": {"objects": len(records), "meshes": len(plan.meshes), "materials": len(plan.materials)},
        "full": full,
    }

    # One real edit: a translation of the first object outside instances, from the session layer.
    (edited,) = [i for i, o in enumerate(records) if not o["instance_context"] and o["mesh"] is not None][:1]
    source = records[edited]["source"]
    edits = []
    for repeat in range(args.repeats):
        steps: dict[str, float] = {}
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            op = UsdGeom.Xformable(stage.GetPrimAtPath(source)).AddTranslateOp(opSuffix=f"b6_{repeat}")
            op.Set(Gf.Vec3d(0.01, 0, 0))
        snapshot = timed(steps, "incremental capture", lambda: bridge.capture(ALAB_TIME, incremental=True))
        plan = timed(steps, "planning", partial(native.build_plan, snapshot))
        display, replaced = replacement(
            update, plan, display, collection, update.Unit(objects=frozenset({edited})), update.UserPolicy.REPOINT
        )
        steps |= {f"replace {step}": value for step, value in replaced["steps"].items()}
        steps["total"] = steps["incremental capture"] + steps["planning"] + replaced["steps"]["total"]
        edits.append({"steps": steps, "changed": replaced["changed"]})
    results["edit"] = {"source": source, "median": median_steps(edits), "runs": edits}

    units = update.sample_units(records)
    replaced_units: dict[str, Any] = {}
    for name, unit in units.items():
        policies = [update.UserPolicy.REPOINT]
        if unit.meshes or unit.materials:
            policies.append(update.UserPolicy.REPLACE)
        for users in policies:
            runs = []
            for _ in range(args.repeats):
                display, run = replacement(update, plan, display, collection, unit, users)
                runs.append(run)
            replaced_units[f"{name} ({users})"] = {"changed": runs[0]["changed"], "median": median_steps(runs)}
    results["units"] = replaced_units
    bridge.release()

    out.mkdir(parents=True, exist_ok=True)
    (out / "updates.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({k: v for k, v in results.items() if k != "edit"} | {"edit": results["edit"]["median"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
