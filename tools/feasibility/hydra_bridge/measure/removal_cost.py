"""M5 Phase F (F2): what the shared removal costs (removal.remove_unused), in fresh Blender binary processes.

    uv run python tools/feasibility/hydra_bridge/measure/removal_cost.py [--scenes updates alab] [--repeats 3]

Retirement, disposal, and a cleanup retry share removal.remove_unused, which reads users once with bpy.data.user_map
and removes a level at a time, users first, each level in one bpy.data.batch_remove call, halved when that call
raises until each datablock that fails is alone. Each run builds the baseline's display (object_display.py) twice, as a
synchronization again holds it before retirement: the published one and the prepared one. Then, removing from the
published one, with its objects unlinked from their collection first, as publication unlinks them:

- one call's fixed cost: batch_remove of one new, unlinked empty, FIXED times;
- units of 1 and UNIT objects, through remove_unused, and the user_map of the same datablocks before each;
- a unit of UNIT objects one of which fails to be removed, injected by wrapping the module's _batch_remove: through
  remove_unused, which halves the failing call; and, for comparison, one call per datablock after the failed call,
  which the removal made before M5 Phase F;
- the rest of the display, every object, shear parent, mesh, and material left, through remove_unused, each level's
  call timed by the wrapper.

Global undo is on, as in a session with a window, unless --undo-off. Raw runs go to <out>/runs/, the summary to
<out>/summary.json and summary.md. Expects the module built by build.py in build/hydra-bridge/.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import bpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
# Import display implementation modules from the bridge directory first.
sys.path[:0] = [str(HERE.parent), str(HERE), str(ROOT / "tools")]

FIXED = 10
UNIT = 100
SCENES = ["updates", "alab"]  # run_benchmarks.py's groups


def run_once(blender: str, config: dict[str, Any], work: Path, timeout: float) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    (work / "config.json").write_text(json.dumps(config))
    command = [
        blender,
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(Path(__file__).resolve()),
        "--",
        "child",
        str(work / "config.json"),
    ]
    env = {**os.environ, "BLENDER_USER_RESOURCES": str(work / "user")}
    try:
        with (work / "log.txt").open("w") as log:
            run = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=timeout)
        returncode: int | None = run.returncode
    except subprocess.TimeoutExpired:
        returncode = None
    result_path = work / "result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else None
    log_text = (work / "log.txt").read_text(errors="replace")
    return {"config": config, "returncode": returncode, "result": result, "log tail": log_text[-3000:]}


def _one_call_each(remove: Callable[[Sequence[bpy.types.ID]], None], datablocks: Sequence[bpy.types.ID]) -> int:
    """Remove datablocks in one call, and if it fails, one call each; how many fail."""
    from proscenium.binding.persistence import id_property_records

    try:
        remove(datablocks)
    except Exception:  # noqa: BLE001 - which failed is found one at a time below
        pass
    else:
        return 0
    failed = 0
    for datablock in datablocks:
        if not id_property_records.alive(datablock):  # removed by the failed call
            continue
        try:
            remove([datablock])
        except Exception:  # noqa: BLE001
            failed += 1
    return failed


def child(config: dict[str, Any]) -> None:
    """One run, its result written where the config says."""
    import bpy

    sys.path[:0] = [config["module_dir"], str(ROOT / "src")]
    import _hydra_bridge as native  # ty: ignore[unresolved-import] - built into build/hydra-bridge
    import object_display
    from pxr import Usd

    from proscenium.binding.persistence import id_property_records
    from proscenium.synchronization import datablock_removal

    bpy.ops.wm.read_factory_settings(use_empty=True)
    preferences: Any = bpy.context.preferences  # never None in a running Blender
    preferences.edit.use_global_undo = config["undo"]
    scene: Any = bpy.context.scene
    view_layer: Any = bpy.context.view_layer  # never None with a scene
    scene.frame_set(int(config["time"]))
    stage = Usd.Stage.Open(config["scene"])
    bridge = native.Bridge(stage)
    plan = native.build_plan(bridge.capture(config["time"]), point_instancers=config["point_instancers"])
    published = bpy.data.collections.new("Published")
    prepared = bpy.data.collections.new("Prepared")
    displays = []
    for collection in (published, prepared):
        scene.collection.children.link(collection)
        displays.append(object_display.apply(plan, collection))
    view_layer.update()
    display = displays[0]
    result: dict[str, Any] = {
        "file datablocks": sum(len(c) for c in (bpy.data.objects, bpy.data.meshes, bpy.data.materials)),
        "display objects": len(published.all_objects),
    }

    calls: list[dict[str, float]] = []
    failing: set[int] = set()  # session_uids of the datablocks whose removal fails
    batch_remove = datablock_removal._batch_remove  # noqa: SLF001 - the module's one call to Blender

    def timed(datablocks: Sequence[bpy.types.ID]) -> None:
        if failing & {d.session_uid for d in datablocks}:
            calls.append({"datablocks": len(datablocks), "s": 0.0, "failed": 1})
            raise RuntimeError("injected removal failure")
        start = time.perf_counter()
        batch_remove(datablocks)
        calls.append({"datablocks": len(datablocks), "s": time.perf_counter() - start})

    datablock_removal._batch_remove = timed  # noqa: SLF001  # ty: ignore[invalid-assignment] - a patch, for measurement

    fixed = []
    for _ in range(FIXED):
        empty = bpy.data.objects.new("Fixed cost", None)
        start = time.perf_counter()
        bpy.data.batch_remove([empty])
        fixed.append(time.perf_counter() - start)
    result["fixed s"] = fixed

    objects = [o for o in display.objects if o.parent is None]  # never a shear parent's child, left with no parent
    taken = iter(objects)

    def unlinked(count: int) -> dict[int, bpy.types.ID]:
        unit = list(itertools.islice(taken, count))
        for obj in unit:
            published.objects.unlink(obj)
        view_layer.update()
        return dict(enumerate(unit))

    def removed(name: str, unit: dict[Any, bpy.types.ID], remove: Callable[[], Any]) -> None:
        calls.clear()
        start = time.perf_counter()
        users = bpy.data.user_map(subset=list(unit.values()))
        user_map_s = time.perf_counter() - start
        assert len(users) == len(unit)
        start = time.perf_counter()
        outcome = remove()
        result[name] = {
            "datablocks": len(unit),
            "user_map s": user_map_s,
            "s": time.perf_counter() - start,
            "calls": list(calls),
            "outcome": outcome,
        }

    def summary(outcome: datablock_removal.RemovalOutcome) -> dict[str, int]:
        return {
            "removed": len(outcome.removed_keys),
            "released": len(outcome.released_keys),
            "pending": len(outcome.pending_reasons_by_key),
        }

    for name, count in (("one object", 1), (f"{UNIT} objects", UNIT)):
        unit = unlinked(count)
        removed(name, unit, lambda unit=unit: summary(datablock_removal.remove_unused(unit)))
    for name in ("halving", "one call each"):
        unit = unlinked(UNIT)
        failing.clear()
        failing.add(unit[UNIT // 2].session_uid)
        if name == "halving":
            removed(name, unit, lambda unit=unit: summary(datablock_removal.remove_unused(unit)))
        else:
            removed(name, unit, lambda unit=unit: {"pending": _one_call_each(timed, list(unit.values()))})
    failing.clear()
    unlinked(len(objects))
    parents = list(published.all_objects)  # the shear parents, still linked
    for obj in parents:
        published.objects.unlink(obj)
    rest: dict[int, bpy.types.ID] = {d.session_uid: d for d in parents}
    rest |= {o.session_uid: o for o in objects if id_property_records.alive(o)}
    rest |= {m.session_uid: m for m in display.meshes} | {m.session_uid: m for m in display.materials}
    rest |= {o.data.session_uid: o.data for o in rest.values() if isinstance(o, bpy.types.Object) and o.data}
    view_layer.update()
    removed("rest of the display", rest, lambda: summary(datablock_removal.remove_unused(rest)))
    bridge.release()
    result["blender version"] = bpy.app.version_string
    Path(config["result"]).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")


def _stats(values: list[float]) -> dict[str, float]:
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


CASES = ["one object", f"{UNIT} objects", "halving", "one call each", "rest of the display"]


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """By scene: each case's times as a median over the runs, with their range, and the first run's calls."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault(run["config"]["scene name"], []).append(run)
    summary: dict[str, Any] = {}
    for name, group in grouped.items():
        results = [run["result"] for run in group if run["result"]]
        entry: dict[str, Any] = {
            "runs": len(results),
            "failed": [r["log tail"][-300:] for r in group if not r["result"]],
        }
        if results:
            first = results[0]
            entry |= {
                "file datablocks": first["file datablocks"],
                "display objects": first["display objects"],
                "fixed s": _stats([statistics.median(r["fixed s"]) for r in results]),
            }
            for case in CASES:
                calls = first[case]["calls"]
                entry[case] = {
                    "datablocks": first[case]["datablocks"],
                    "outcome": first[case]["outcome"],
                    "user_map s": _stats([r[case]["user_map s"] for r in results]),
                    "s": _stats([r[case]["s"] for r in results]),
                    "calls": len(calls),
                    "levels": [c["datablocks"] for c in calls if len(calls) < 10],
                    "largest call s": _stats([max((c["s"] for c in r[case]["calls"]), default=0.0) for r in results]),
                }
        summary[name] = entry
    return summary


def markdown(summary: dict[str, Any], setup: dict[str, Any]) -> str:
    def cell(stat: dict[str, float], scale: float = 1000.0) -> str:
        median, low, high = (stat[k] * scale for k in ("median", "min", "max"))
        return f"{median:,.1f} ({low:,.1f}-{high:,.1f})"

    names = [name for name, entry in summary.items() if entry["runs"]]
    rows: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("Datablocks in the file (objects, meshes, materials)", lambda e: f"{e['file datablocks']:,}"),
        ("One call of one empty (ms)", lambda e: cell(e["fixed s"])),
    ]
    for case in CASES:
        rows += [
            (
                f"{case}: datablocks; calls",
                lambda e, c=case: f"{e[c]['datablocks']:,}; {e[c]['calls']} {e[c]['levels']}",
            ),
            (f"{case}: outcome", lambda e, c=case: json.dumps(e[c]["outcome"])),
            (f"{case}: user_map (ms)", lambda e, c=case: cell(e[c]["user_map s"])),
            (f"{case}: removal (ms)", lambda e, c=case: cell(e[c]["s"])),
            (f"{case}: its largest call (ms)", lambda e, c=case: cell(e[c]["largest call s"])),
        ]
    lines = [
        "# The shared removal's cost (M5 Phase F, F2)",
        "",
        f"Setup: {json.dumps(setup)}",
        "",
        "Medians over the runs, with their range; calls are the first run's, with each one's datablocks.",
        "",
        "| Measure | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    lines += [f"| {label} | " + " | ".join(value(summary[n]) for n in names) + " |" for label, value in rows]
    lines += [f"\n{name}: failed: {entry['failed'][:1]}" for name, entry in summary.items() if not entry["runs"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    from blender_paths import find_blender

    # Load the benchmark runner's scene and environment helpers by its script path.
    spec = importlib.util.spec_from_file_location("measure_run", HERE / "run_benchmarks.py")
    assert spec is not None and spec.loader is not None
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenes", nargs="+", default=SCENES, help="run_benchmarks.py's scene groups")
    parser.add_argument("--exclude", nargs="*", default=[], help="scenes of those groups to leave out")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--undo-off", action="store_true", help="global undo off")
    parser.add_argument("--timeout", type=float, default=3600.0, help="per run (s)")
    parser.add_argument("--out", type=Path, default=ROOT / "build/hydra-bridge/removal-cost")
    parser.add_argument("--module-dir", type=Path, default=ROOT / "build/hydra-bridge")
    parser.add_argument("--blender", default=find_blender())
    args = parser.parse_args()
    if not args.blender:
        parser.error("no Blender binary found: set BLENDER or pass --blender")
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    out: Path = args.out.resolve()
    (out / "runs").mkdir(parents=True, exist_ok=True)
    found = {name: scene for name, scene in run.scenes(args.scenes, out).items() if name not in args.exclude}
    runs = []
    for repeat in range(args.repeats):
        for name, scene in found.items():
            label = f"{name}-{repeat}"
            work = out / "work" / label
            config = {
                "scene name": name,
                "scene": scene["path"],
                "time": scene["time"],
                "point_instancers": scene.get("point_instancers", True),
                "undo": not args.undo_off,
                "module_dir": str(args.module_dir.resolve()),
                "work": str(work),
                "result": str(work / "result.json"),
            }
            result = run_once(args.blender, config, work, args.timeout)
            (out / "runs" / f"{label}.json").write_text(json.dumps(result) + "\n")
            print(f"{label}: {'ok' if result['returncode'] == 0 and result['result'] else 'failed'}", flush=True)
            runs.append(result)
    setup = {"environment": run.environment(args.blender), "undo": not args.undo_off, "unit": UNIT}
    summary = summarize(runs)
    (out / "summary.json").write_text(json.dumps({"setup": setup, "summary": summary}, indent=2, default=str) + "\n")
    (out / "summary.md").write_text(markdown(summary, setup))
    print(f"summary: {out / 'summary.md'}")
    return 0


if __name__ == "__main__":
    if "--" in sys.argv and sys.argv[sys.argv.index("--") + 1] == "child":
        child(json.loads(Path(sys.argv[sys.argv.index("--") + 2]).read_text()))
    else:
        sys.exit(main())
