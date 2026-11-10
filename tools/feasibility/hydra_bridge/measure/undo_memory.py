"""M5 Phase F (F1): the memory an undo step holds for a published synchronization, in fresh Blender binary processes.

    uv run python tools/feasibility/hydra_bridge/measure/undo_memory.py [--scenes updates alab] [--repeats 3]

M5's synchronization is a full rebuild: it constructs every display resource anew, publishes them, and retires the
ones they replace, then pushes one undo step (lifecycle.md#undo-and-runtime-state). Each run builds the baseline's
display (object_display.py), as the product's first synchronization would, and pushes a step; then EDITS times moves one
object and pushes a step, the cost of a step that changes little; then REBUILDS times rebuilds the whole display from
the same plan, as a synchronization again would, removes the one it replaces, evaluates, and pushes a step. The heap
in use (memory.py) is read before and after each push, so a push's growth is what that step holds, and after each
rebuild and its push, for the growth a synchronization leaves. Each scene also runs as a control with global undo
off, pushing nothing. With undo, one undo and one redo are timed after the steps. Each run saves the .blend
uncompressed, for the file's size beside a step's, and records Blender's undo preferences, which --undo-steps and
--undo-memory-limit set.
Raw runs go to <out>/runs/, the summary to <out>/summary.json and summary.md. Expects the module built by build.py
in build/hydra-bridge/.
"""

from __future__ import annotations

import argparse
import functools
import itertools
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
# Import display implementation modules from the bridge directory first.
sys.path[:0] = [str(HERE.parent), str(HERE), str(ROOT / "tools")]

EDITS = 3
REBUILDS = 4
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
    with (work / "log.txt").open("w") as log:
        returncode = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=timeout).returncode
    result_path = work / "result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else None
    log_text = (work / "log.txt").read_text(errors="replace")
    return {"config": config, "returncode": returncode, "result": result, "log tail": log_text[-3000:]}


def child(config: dict[str, Any]) -> None:
    """One run, its result written where the config says."""
    import bpy

    sys.path.insert(0, config["module_dir"])
    import _hydra_bridge as native  # ty: ignore[unresolved-import] - built into build/hydra-bridge
    import memory
    import object_display
    from pxr import Usd

    bpy.ops.wm.read_factory_settings(use_empty=True)
    preferences: Any = bpy.context.preferences  # never None in a running Blender
    undo = config["undo"]
    preferences.edit.use_global_undo = undo
    for name, value in (("undo_steps", config["undo_steps"]), ("undo_memory_limit", config["undo_memory_limit"])):
        if value is not None:
            setattr(preferences.edit, name, value)
    scene: Any = bpy.context.scene
    view_layer: Any = bpy.context.view_layer  # never None with a scene
    scene.frame_set(int(config["time"]))
    mb = lambda value: None if value is None else value / 2**20  # noqa: E731

    def heap() -> float:
        found = mb(memory.heap_in_use())
        assert found is not None, "no live-heap counter on this platform"
        return found

    stage = Usd.Stage.Open(config["scene"])
    bridge = native.Bridge(stage)
    plan = native.build_plan(bridge.capture(config["time"]), point_instancers=config["point_instancers"])

    def build(name: str) -> tuple[bpy.types.Collection, Any]:
        collection = bpy.data.collections.new(name)
        scene.collection.children.link(collection)
        return collection, object_display.apply(plan, collection)

    def push(message: str) -> dict[str, float]:
        if not undo:
            return {}
        before = heap()
        start = time.perf_counter()
        bpy.ops.ed.undo_push(message=message)
        seconds = time.perf_counter() - start
        return {"push s": seconds, "push MB": heap() - before}

    result: dict[str, Any] = {
        "undo preferences": {
            "steps": preferences.edit.undo_steps,
            "memory limit MB": preferences.edit.undo_memory_limit,
        },
        "heap before MB": heap(),
    }
    collection, display = build("Synchronized 0")
    view_layer.update()
    result["heap built MB"] = heap() - result["heap before MB"]
    result["objects"] = len(collection.all_objects)
    result["datablocks"] = sum(len(c) for c in (bpy.data.objects, bpy.data.meshes, bpy.data.materials))
    result["first"] = push("synchronized 0")
    edits = []
    for index in range(EDITS):
        display.objects[0].location.x += 1.0
        view_layer.update()
        edits.append(push(f"moved one object {index}"))
    result["edits"] = edits
    rebuilds = []
    for index in range(1, REBUILDS + 1):
        before = heap()
        start = time.perf_counter()
        data = {o.data for o in collection.all_objects if o.data is not None}
        replaced: list[bpy.types.ID] = [*collection.all_objects, collection, *data, *display.materials]
        collection, display = build(f"Synchronized {index}")
        bpy.data.batch_remove(replaced)
        view_layer.update()  # as after a publication, so the replaced display's evaluation goes
        step: dict[str, float] = {"rebuild s": time.perf_counter() - start, "rebuild MB": heap() - before}
        step |= push(f"synchronized {index}")
        rebuilds.append(step | {"cycle MB": heap() - before})
    result["rebuilds"] = rebuilds
    result["heap after steps MB"] = heap() - result["heap before MB"]
    for name, call in (("undo", bpy.ops.ed.undo), ("redo", bpy.ops.ed.redo)) if undo else ():
        start = time.perf_counter()
        call()
        result[f"{name} s"] = time.perf_counter() - start
    result["footprint MB"] = mb(memory.footprint(os.getpid()))
    blend = Path(config["work"]) / "synchronized.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=False)
    result["blend MB"] = mb(blend.stat().st_size)
    blend.unlink()
    bridge.release()
    result["blender version"] = bpy.app.version_string
    Path(config["result"]).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")


def _stats(values: list[float]) -> dict[str, float]:
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def _each(results: list[dict[str, Any]], key: str, steps: str | None = None) -> dict[str, float] | None:
    """Key's statistics over results: each run's own value, or its median over its steps."""
    found = [statistics.median(s[key] for s in r[steps]) if steps else r.get(key) for r in results]
    values = [v for v in found if v is not None]
    return _stats(values) if len(values) == len(found) else None


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """By scene and undo: each measure's median over the runs, with its range; a step's is each run's median step."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        config = run["config"]
        parts = [config["scene name"], f"undo {'on' if config['undo'] else 'off'}"]
        if config["undo_steps"] is not None:
            parts.append(f"{config['undo_steps']} steps")
        if config["undo_memory_limit"] is not None:
            parts.append(f"limit {config['undo_memory_limit']} MB")
        grouped.setdefault(", ".join(parts), []).append(run)
    summary: dict[str, Any] = {}
    for name, group in grouped.items():
        results = [run["result"] for run in group if run["result"]]
        entry: dict[str, Any] = {
            "runs": len(results),
            "failed": [r["log tail"][-300:] for r in group if not r["result"]],
        }
        if not results:
            summary[name] = entry
            continue
        each = functools.partial(_each, results)
        entry |= {
            "objects": results[0]["objects"],
            "datablocks": results[0]["datablocks"],
            "undo preferences": results[0]["undo preferences"],
            "heap built MB": each("heap built MB"),
            "blend MB": each("blend MB"),
            "rebuild cycle MB": each("cycle MB", "rebuilds"),
            "heap after steps MB": each("heap after steps MB"),
            "rebuild s": each("rebuild s", "rebuilds"),
        }
        if results[0]["first"]:
            entry |= {
                "first push MB": _stats([r["first"]["push MB"] for r in results]),
                "edit push MB": each("push MB", "edits"),
                "rebuild push MB": each("push MB", "rebuilds"),
                "first push s": _stats([r["first"]["push s"] for r in results]),
                "edit push s": each("push s", "edits"),
                "rebuild push s": each("push s", "rebuilds"),
                "undo s": each("undo s"),
                "redo s": each("redo s"),
            }
        summary[name] = entry
    return summary


def markdown(summary: dict[str, Any], setup: dict[str, Any]) -> str:
    def cell(stat: dict[str, float] | None, scale: float = 1.0, digits: int = 0) -> str:
        if stat is None:
            return "-"
        median, low, high = (stat[k] * scale for k in ("median", "min", "max"))
        return f"{median:,.{digits}f} ({low:,.{digits}f}-{high:,.{digits}f})"

    rows = [
        ("Objects", lambda e: f"{e['objects']:,}"),
        ("Objects, meshes, and materials", lambda e: f"{e['datablocks']:,}"),
        ("Heap built (MB)", lambda e: cell(e["heap built MB"])),
        ("`.blend`, uncompressed (MB)", lambda e: cell(e["blend MB"])),
        ("First push (MB)", lambda e: cell(e.get("first push MB"))),
        ("Push after moving one object (MB)", lambda e: cell(e.get("edit push MB"), digits=1)),
        ("Push after a rebuild (MB)", lambda e: cell(e.get("rebuild push MB"))),
        ("A rebuild and its push (MB)", lambda e: cell(e["rebuild cycle MB"], digits=1)),
        ("Heap after every step (MB)", lambda e: cell(e["heap after steps MB"])),
        ("First push (ms)", lambda e: cell(e.get("first push s"), 1000)),
        ("Push after moving one object (ms)", lambda e: cell(e.get("edit push s"), 1000)),
        ("Push after a rebuild (ms)", lambda e: cell(e.get("rebuild push s"), 1000)),
        ("Rebuild (s)", lambda e: cell(e["rebuild s"], digits=2)),
        ("Undo (ms)", lambda e: cell(e.get("undo s"), 1000)),
        ("Redo (ms)", lambda e: cell(e.get("redo s"), 1000)),
    ]
    names = [name for name, entry in summary.items() if entry["runs"]]
    lines = [
        "# The undo step's memory for a published synchronization (M5 Phase F, F1)",
        "",
        f"Setup: {json.dumps(setup)}",
        "",
        "Medians over the runs, with their range; a step's is each run's median over its steps.",
        "",
        "| Measure | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    lines += [f"| {label} | " + " | ".join(value(summary[n]) for n in names) + " |" for label, value in rows]
    lines += [f"\n{name}: failed: {entry['failed'][:1]}" for name, entry in summary.items() if not entry["runs"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    import importlib.util

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
    parser.add_argument("--undo-steps", type=int, help="Blender's undo steps preference (default: as found)")
    parser.add_argument("--undo-memory-limit", type=int, help="its undo memory limit, MB (default: as found)")
    parser.add_argument("--no-control", action="store_true", help="skip the runs with global undo off")
    parser.add_argument("--timeout", type=float, default=3600.0, help="per run (s)")
    parser.add_argument("--out", type=Path, default=ROOT / "build/hydra-bridge/undo-memory")
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
        for (name, scene), undo in itertools.product(found.items(), (True,) if args.no_control else (True, False)):
            label = f"{name}-undo-{'on' if undo else 'off'}-{repeat}"
            work = out / "work" / label
            config = {
                "scene name": name,
                "undo": undo,
                "undo_steps": args.undo_steps,
                "undo_memory_limit": args.undo_memory_limit,
                "scene": scene["path"],
                "time": scene["time"],
                "point_instancers": scene.get("point_instancers", True),
                "module_dir": str(args.module_dir.resolve()),
                "work": str(work),
                "result": str(work / "result.json"),
            }
            result = run_once(args.blender, config, work, args.timeout)
            (out / "runs" / f"{label}.json").write_text(json.dumps(result) + "\n")
            print(f"{label}: {'ok' if result['returncode'] == 0 and result['result'] else 'failed'}", flush=True)
            runs.append(result)
    setup = {"environment": run.environment(args.blender), "edits": EDITS, "rebuilds": REBUILDS}
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
