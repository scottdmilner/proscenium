"""M6 Phase F (F1 to F3): the core's capture and planning, split by stage, with memory, in the Blender binary.

    uv run python tools/feasibility/hydra_bridge/measure/evaluation_cost.py [--scenes alab] [--files SCENE.usd ...] \
        [--repeats 3]

Each run opens the scene, attaches it to a binding's stages (proscenium.binding.source_access.stages) and acquires
the evaluation stage under load-all, as a synchronization does, then ITERATIONS times: builds the scene-index chain,
captures the scene's time code (a file's start time code), releases the chain, plans the snapshot under the default
settings and a unit scale of 1, plans it again with coordinate conversion on and drops that plan, reads the plan
across the boundary once, and groups its copies in batches of at least BATCH_MINIMUM, then drops the snapshot and
plan. Reading the plan is every tuple property converted once (each description's extent with it), every buffer
viewed, and the buffers the stub application layer turns into lists turned into lists. Then per copy (F3): every
field of the tuples' elements read, each copy's object index from a fresh read of the correspondence tuple and from
the copy_objects buffer, the same content, and each copy's world matrix made from the buffer as the stub makes it.
Each stage is timed by wall
clock and by the process's CPU time, all threads', and the live heap (memory.heap_in_use) is read after it. Raw runs
go to <out>/runs/, the summary to <out>/summary.json and summary.md.
"""

from __future__ import annotations

import argparse
import importlib.util
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
sys.path[:0] = [str(HERE), str(ROOT / "tools")]

ITERATIONS = 3  # chain, capture, plan, and read in one process: the first, then as a synchronization again
SCENES = ["alab"]  # run.py's groups
BATCH_MINIMUM = 5  # DECISIONS.md "Display representation"
STAGES = ["chain", "capture", "release chain", "plan", "plan, converting", "drop converted", "read tuples"]
STAGES += [
    "read buffers",
    "buffers to lists",
    "correspondence fields",
    "resource fields",
    "objects from the tuple",
    "objects from the buffer",
]
STAGES += ["matrices from the buffer", "batch groups", "drop"]
TUPLES = ["partitions", "resources", "correspondence", "geometries", "diagnostics"]
BUFFERS = [
    "copy_worlds",
    "copy_objects",
    "copy_geometries",
    "copy_placeholders",
    "placeholder_bounds",
    "copy_viewport",
    "copy_render",
    "copy_shears",
    "shear_parent_worlds",
    "shear_object_bases",
]
LISTED = ["copy_objects", "copy_geometries", "copy_placeholders", "placeholder_bounds", "copy_viewport"]
LISTED += ["copy_render", "copy_shears"]  # the buffers application.py calls tolist() on


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
    load = os.getloadavg()[0]  # the machine's other work, which the record reports
    with (work / "log.txt").open("w") as log:
        returncode = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=timeout).returncode
    result_path = work / "result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else None
    log_text = (work / "log.txt").read_text(errors="replace")
    return {"config": config, "returncode": returncode, "result": result, "load": load, "log tail": log_text[-3000:]}


def child(config: dict[str, Any]) -> None:
    """One run, its result written where the config says."""
    import gc

    import bpy
    import memory
    from mathutils import Matrix

    sys.path.insert(0, str(ROOT / "src"))
    from pxr import Usd, UsdGeom

    from proscenium.binding.source_access import stages
    from proscenium.core import _core
    from proscenium.synchronization import application

    bpy.ops.wm.read_factory_settings(use_empty=True)
    marks: list[dict[str, Any]] = []
    last = [time.perf_counter(), time.process_time()]

    def mark(stage: str) -> None:
        wall, cpu = time.perf_counter(), time.process_time()
        marks.append({"stage": stage, "s": wall - last[0], "cpu s": cpu - last[1], "heap": memory.heap_in_use()})
        last[:] = [time.perf_counter(), time.process_time()]  # the heap read isn't the next stage's

    mark("start")
    stage = Usd.Stage.Open(config["scene"])
    mark("open")
    binding_stages = stages.BindingStages()
    binding_stages.attach(stage)
    evaluation_stage = binding_stages.acquire_evaluation_stage(stages.PayloadPolicy.LOAD_ALL)
    mark("acquire")
    settings = _core.PlanSettings(("default", "proxy"), ("default", "render"), False)
    converting = _core.PlanSettings(("default", "proxy"), ("default", "render"), True)
    context = _core.PlanningContext(1.0, application.REPRESENTATION_VERSION)
    setup = list(marks)
    iterations = []
    for _ in range(ITERATIONS):
        marks.clear()
        mark("start")
        chain = _core.SceneIndexChain(evaluation_stage)
        mark("chain")
        snapshot = chain.capture(Usd.TimeCode(config["time"]))
        mark("capture")
        chain.release()
        del chain
        mark("release chain")
        plan = _core.plan(snapshot, settings, context)
        mark("plan")
        converted = _core.plan(snapshot, converting, context)
        mark("plan, converting")
        del converted
        mark("drop converted")
        read = {name: getattr(plan, name) for name in TUPLES}
        extents = [memoryview(g.extent) for g in read["geometries"]]
        mark("read tuples")
        views = {name: memoryview(getattr(plan, name)) for name in BUFFERS}
        mark("read buffers")
        lists = {name: views[name].tolist() for name in LISTED}
        mark("buffers to lists")
        entry_fields = [(c.element, c.source, c.instance_context) for c in read["correspondence"]]
        mark("correspondence fields")
        resource_fields = [(r.role, r.entity, r.place, r.covers, r.uses) for r in read["resources"]]
        mark("resource fields")
        from_tuple = [c.element for c in plan.correspondence]
        mark("objects from the tuple")
        from_buffer = memoryview(plan.copy_objects).tolist()
        mark("objects from the buffer")
        assert from_tuple == from_buffer
        worlds = views["copy_worlds"]
        matrices = []
        for copy in range(plan.copy_count):  # as application._matrix_from_buffer
            columns = worlds[16 * copy : 16 * copy + 16].tolist()
            matrices.append(Matrix([columns[i : i + 4] for i in range(0, 16, 4)]).transposed())
        mark("matrices from the buffer")
        groups, singles = plan.batch_groups(BATCH_MINIMUM)
        members = [len(memoryview(g.members)) for g in groups]
        mark("batch groups")
        contexts = [entry.instance_context for entry in read["correspondence"]]
        counts = {
            "copies": plan.copy_count,
            "resources": len(read["resources"]),
            "geometries": len(read["geometries"]),
            "placeholders": len(views["placeholder_bounds"]) // 6,
            "shears": len(views["shear_object_bases"]) // 16,
            "diagnostics": len(read["diagnostics"]),
            "instanced copies": sum(1 for c in contexts if c),
            "instance contexts": len(set(contexts) - {()}),
            "batch groups": len(groups),
            "batched copies": sum(members),
            "largest batch group": max(members, default=0),
            "single copies": len(memoryview(singles)),
        }
        del (
            read,
            extents,
            views,
            lists,
            entry_fields,
            resource_fields,
            from_tuple,
            from_buffer,
            worlds,
            matrices,
            groups,
            singles,
            contexts,
            plan,
            snapshot,
        )
        gc.collect()
        mark("drop")
        iterations.append({"marks": list(marks), "counts": counts})
    stage_units = {"metersPerUnit": UsdGeom.GetStageMetersPerUnit(stage), "upAxis": UsdGeom.GetStageUpAxis(stage)}
    stage_units["metersPerUnit authored"] = UsdGeom.StageHasAuthoredMetersPerUnit(stage)
    binding_stages.release()
    result = {
        "setup": setup,
        "stage units": stage_units,
        "iterations": iterations,
        "peaks": memory.own_peaks(),
        "threads": os.cpu_count(),
        "blender version": bpy.app.version_string,
    }
    Path(config["result"]).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")


def _stats(values: list[float]) -> dict[str, float]:
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def _by_stage(iteration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Stage -> its mark, with the heap it added and the heap at its end, from the iteration's start."""
    marks = iteration["marks"]
    start = marks[0]["heap"]
    found = {}
    for before, mark in zip([None, *marks], marks, strict=False):
        previous = start if before is None else before["heap"]
        heap = mark["heap"]
        found[mark["stage"]] = mark | {
            "added": None if heap is None or previous is None else heap - previous,
            "held": None if heap is None or start is None else heap - start,
        }
    return found


def _per_run(runs_stages: list[list[dict[str, Any]]], stage: str, key: str) -> list[float]:
    """Each run's median of key over its iterations' stage, for the median and range over runs."""
    return [statistics.median(i[stage][key] for i in r) for r in runs_stages if r[0][stage][key] is not None]


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """By scene, the first iteration's and the later ones' stages over the runs."""
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
        if not results:
            summary[name] = entry
            continue
        entry["counts"] = results[0]["iterations"][0]["counts"]
        entry["stage units"] = results[0]["stage units"]
        entry["load"] = _stats([run["load"] for run in group])
        entry["peaks"] = {k: _stats([r["peaks"][k] for r in results]) for k in results[0]["peaks"]}
        setups = [_by_stage({"marks": r["setup"]}) for r in results]
        entry["setup"] = {
            stage: {
                k: _stats([s[stage][k] for s in setups])
                for k in ("s", "cpu s", "held")
                if setups[0][stage][k] is not None
            }
            for stage in ("open", "acquire")
        }
        for label, picked in (("first", lambda r: r["iterations"][:1]), ("again", lambda r: r["iterations"][1:])):
            stages_found = [[_by_stage(i) for i in picked(r)] for r in results]
            table = {}
            for stage in STAGES:
                table[stage] = {
                    k: _stats(v) for k in ("s", "cpu s", "added", "held") if (v := _per_run(stages_found, stage, k))
                }
            entry[label] = table
        summary[name] = entry
    return summary


def markdown(summary: dict[str, Any], setup: dict[str, Any]) -> str:
    def cell(stat: dict[str, float] | None, scale: float, digits: int = 0) -> str:
        if not stat:
            return ""
        median, low, high = (stat[k] * scale for k in ("median", "min", "max"))
        return f"{median:,.{digits}f} ({low:,.{digits}f}–{high:,.{digits}f})"

    lines = ["# Capture and planning, by stage (M6 Phase F, F1)", "", f"Setup: {json.dumps(setup)}", ""]
    for name, entry in summary.items():
        if not entry["runs"]:
            lines += [f"## {name}", "", f"failed: {entry['failed'][:1]}", ""]
            continue
        peaks = ", ".join(f"{k} {cell(v, 1e-6)} MB" for k, v in entry["peaks"].items())
        load = cell(entry["load"], 1, 1)
        lines += [f"## {name}: {entry['runs']} runs, {json.dumps(entry['counts'])}", "", f"Peaks: {peaks}", ""]
        lines += [
            f"Load average at each run's start: {load}",
            "",
            f"Stage units: {json.dumps(entry['stage units'])}",
            "",
        ]
        for label in ("setup", "first", "again"):
            lines += [
                f"### {label}",
                "",
                "| Stage | Wall (ms) | Cores | Heap added (MB) | Heap held (MB) |",
                "|---|---|---|---|---|",
            ]
            for stage, stat in entry[label].items():
                cores = stat["cpu s"]["median"] / stat["s"]["median"] if stat["s"]["median"] else 0.0
                lines.append(
                    f"| {stage} | {cell(stat['s'], 1e3, 1)} | {cores:.1f} | {cell(stat.get('added'), 1e-6)} "
                    f"| {cell(stat.get('held'), 1e-6)} |"
                )
            lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    from blender_paths import find_blender

    # run.py's scenes and environment; the bridge has a run.py of its own, which comes first on the path.
    spec = importlib.util.spec_from_file_location("measure_run", HERE / "run.py")
    assert spec is not None and spec.loader is not None
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenes", nargs="+", default=SCENES, help="run.py's scene groups")
    parser.add_argument("--files", nargs="*", default=[], help="scene files, each captured at its start time code")
    parser.add_argument("--exclude", nargs="*", default=[], help="scenes of those groups to leave out")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=1800.0, help="per run (s)")
    parser.add_argument("--out", type=Path, default=ROOT / "build/hydra-bridge/evaluation-cost")
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
    for file in args.files:
        from pxr import Usd

        found[Path(file).stem] = {"path": file, "time": Usd.Stage.Open(file).GetStartTimeCode()}
    runs = []
    for repeat in range(args.repeats):
        for name, scene in found.items():
            label = f"{name}-{repeat}"
            work = out / "work" / label
            config = {
                "scene name": name,
                "scene": scene["path"],
                "time": scene["time"],
                "work": str(work),
                "result": str(work / "result.json"),
            }
            result = run_once(args.blender, config, work, args.timeout)
            (out / "runs" / f"{label}.json").write_text(json.dumps(result) + "\n")
            print(f"{label}: {'ok' if result['returncode'] == 0 and result['result'] else 'failed'}", flush=True)
            runs.append(result)
    setup = {"environment": run.environment(args.blender), "iterations": ITERATIONS}
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
