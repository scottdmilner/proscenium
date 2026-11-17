"""M7 Phase C (C2): incremental capture from a kept chain against a full re-read, in the Blender binary.

    uv run python tools/feasibility/hydra_bridge/measure/incremental_capture_cost.py [--scenes alab] [--repeats 3] \
        [--label NAME]

Each run opens the scene, attaches it to a binding's stages and acquires the evaluation stage under load-all, as a
synchronization does, builds the core's scene-index chain, and captures the scene's time code. Then, from that kept
chain, in order: a capture with nothing changed; one after a translate op is added, in the session layer, to the first
mesh outside native instances (an edit to one prim's transform); one a time code later (a time change); and one after
that mesh's parent is deactivated (a resync). Each capture is timed by wall clock, with the prims it copied, and so is
a full re-read of the same state, a new chain built and captured, whose plan must equal the kept chain's: its copy
count and world-matrix bytes are compared. --label names the core build measured, such as one ending in notice
batching (HdsiPrimTypeNoticeBatchingSceneIndex). Raw runs go to <out>/runs/, the summary to <out>/summary.json and
summary.md.
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

SCENES = ["alab"]  # run_benchmarks.py's groups
STEPS = ["unchanged", "one transform", "time change", "resync"]


def run_once(blender: str, config: dict[str, Any], work: Path, timeout: float) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    (work / "config.json").write_text(json.dumps(config))
    command = [blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python"]
    command += [str(Path(__file__).resolve()), "--", "child", str(work / "config.json")]
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
    sys.path.insert(0, str(ROOT / "src"))
    from pxr import Usd, UsdGeom

    from proscenium_sync.core import _core
    from proscenium_sync.source_access import binding_settings, stages
    from proscenium_sync.synchronization import application

    stage = Usd.Stage.Open(config["scene"])
    binding_stages = stages.BindingStages()
    binding_stages.attach(stage)
    evaluation_stage = binding_stages.acquire_evaluation_stage(binding_settings.PayloadPolicy.LOAD_ALL)
    settings = _core.PlanSettings(("default", "proxy"), ("default", "render"), False)
    context = _core.PlanningContext(1.0, application.REPRESENTATION_VERSION)

    def planned(snapshot: _core.Snapshot) -> tuple[int, bytes]:
        plan = _core.plan(snapshot, settings, context)
        return plan.copy_count, bytes(memoryview(plan.copy_world_matrices))

    start = time.perf_counter()
    chain = _core.SceneIndexChain(evaluation_stage)
    built = time.perf_counter() - start
    start = time.perf_counter()
    first = chain.capture(Usd.TimeCode(config["time"]))
    result: dict[str, Any] = {
        "chain s": built,
        "first capture s": time.perf_counter() - start,
        "prims": first._copied_prim_count,  # noqa: SLF001 - exposed for measurements
        "steps": {},
    }
    mesh = next(
        p
        for p in Usd.PrimRange(evaluation_stage.GetPseudoRoot())
        if p.GetTypeName() == "Mesh" and not p.IsInstanceProxy() and not p.IsInPrototype()
    )
    result["edited"] = str(mesh.GetPath())
    time_code = config["time"]
    for step in STEPS:
        with Usd.EditContext(evaluation_stage, evaluation_stage.GetSessionLayer()):
            if step == "one transform":
                UsdGeom.Xformable(mesh).AddTranslateOp(opSuffix="probe").Set((0.5, 0, 0))
            elif step == "time change":
                time_code += 1.0
            elif step == "resync":
                mesh.GetParent().SetActive(False)
        start = time.perf_counter()
        snapshot = chain.capture(Usd.TimeCode(time_code))
        incremental = time.perf_counter() - start
        start = time.perf_counter()
        fresh = _core.SceneIndexChain(evaluation_stage)
        full = fresh.capture(Usd.TimeCode(time_code))
        full_seconds = time.perf_counter() - start
        result["steps"][step] = {
            "incremental s": incremental,
            "copied": snapshot._copied_prim_count,  # noqa: SLF001
            "full re-read s": full_seconds,
            "plans equal": planned(snapshot) == planned(full),
        }
        fresh.release()
    chain.release()
    Path(config["result"]).write_text(json.dumps(result))


def _spread(values: list[float]) -> list[float]:
    return [min(values), statistics.median(values), max(values)]


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_scene: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        if run["result"]:
            by_scene.setdefault(run["config"]["scene name"], []).append(run["result"])
    summary: dict[str, Any] = {}
    for name, results in by_scene.items():
        summary[name] = {
            "runs": len(results),
            "prims": sorted({r["prims"] for r in results}),
            "chain s": _spread([r["chain s"] for r in results]),
            "first capture s": _spread([r["first capture s"] for r in results]),
            "loads": [round(run["load"], 1) for run in runs if run["config"]["scene name"] == name],
            "steps": {
                step: {
                    "incremental s": _spread([r["steps"][step]["incremental s"] for r in results]),
                    "copied": sorted({r["steps"][step]["copied"] for r in results}),
                    "full re-read s": _spread([r["steps"][step]["full re-read s"] for r in results]),
                    "plans equal": all(r["steps"][step]["plans equal"] for r in results),
                }
                for step in STEPS
            },
        }
    return summary


def markdown(summary: dict[str, Any], setup: dict[str, Any]) -> str:
    lines = [f"# Incremental capture ({setup['label']})", ""]
    for name, scene in summary.items():
        lines += [f"## {name}: {scene['prims']} prims, {scene['runs']} runs, loads {scene['loads']}", ""]
        chain, first = (", ".join(f"{s:.3f}" for s in scene[key]) for key in ("chain s", "first capture s"))
        lines += [f"chain {chain} s, first capture {first} s (min, median, max)", ""]
        lines += ["| step | incremental s (min, median, max) | copied | full re-read s | plans equal |"]
        lines += ["|---|---|---|---|---|"]
        for step, row in scene["steps"].items():
            incremental = ", ".join(f"{s:.4f}" for s in row["incremental s"])
            full = ", ".join(f"{s:.3f}" for s in row["full re-read s"])  # min, median, max
            lines.append(f"| {step} | {incremental} | {row['copied']} | {full} | {row['plans equal']} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    from blender_paths import find_blender

    spec = importlib.util.spec_from_file_location("measure_run", HERE / "run_benchmarks.py")
    assert spec is not None and spec.loader is not None
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenes", nargs="+", default=SCENES, help="run_benchmarks.py's scene groups")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--label", default="the core as built", help="which core build is measured")
    parser.add_argument("--timeout", type=float, default=1800.0, help="per run (s)")
    parser.add_argument("--out", type=Path, default=ROOT / "build/hydra-bridge/incremental-capture")
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
    runs = []
    for repeat in range(args.repeats):
        for name, scene in run.scenes(args.scenes, out).items():
            label = f"{name}-{repeat}"
            work = out / "work" / label
            config = {"scene name": name, "scene": scene["path"], "time": scene["time"]}
            config["result"] = str(work / "result.json")
            result = run_once(args.blender, config, work, args.timeout)
            (out / "runs" / f"{label}.json").write_text(json.dumps(result) + "\n")
            print(f"{label}: {'ok' if result['returncode'] == 0 and result['result'] else 'failed'}", flush=True)
            runs.append(result)
    setup = {"environment": run.environment(args.blender), "label": args.label}
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
