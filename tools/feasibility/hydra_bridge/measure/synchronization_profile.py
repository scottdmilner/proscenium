"""The product's synchronizations, cache call, and cached frames, step by step, with memory, in the Blender binary.

    uv run python tools/feasibility/hydra_bridge/measure/synchronization_profile.py [--scenes updates alab] \
        [--exclude updates-100] [--repeats 3] [--undo on off] [--runtimes binary wheel] [--no-full-rebuild]

M7 plan, Phase G (items 1, 2, 3, and 5). Each run makes a binding through the API (proscenium_sync.api.bindings),
attaches the scene's stage, and makes these calls in order (CALLS), each one step:
- synchronize: the first synchronization, at the scene's time code;
- unchanged: synchronizing again with nothing changed;
- move: after a translate op is added, in the session layer, to the first mesh outside native instances;
- hide: after the second such mesh is made invisible, in the session layer;
- reload: the binding's reload of its source layers, then a synchronization (timed together, and each apart);
- full rebuild: a synchronization with full_rebuild, which rereads the source through a new chain and prepares every
  partition anew (left out with --no-full-rebuild);
- cache: CACHED later time codes;
- cached frame, back, revisit: the scene's frame set to the first cached time code, back to the synchronized one,
  then to the cached one again.
Global undo is on, or as --undo says, and the API pushes its step as it would with a window (its _undo_steps_enabled
patched true, since background mode pushes none). --runtimes runs it in the bpy wheel too. The add-on isn't
registered, so no handler runs on a frame change.

Each function the calls reach their steps through is timed by wrapping it (STEPS), so a time includes the functions
it calls; one called more than once is summed, with its calls counted. The undo push's growth of the heap in use
(memory.py) is read around each push. After each step, outside its time, the heap is read, then the view layer
updated, as a window's redraw would, timed, and the heap read again, since the depsgraph holds evaluated copies until
its next evaluation. At the end, the heap freed by releasing the binding's held plans, with how many it held. Raw runs
go to <out>/runs/, the summary to <out>/summary.json and summary.md.
"""

from __future__ import annotations

import argparse
import functools
import gc
import importlib
import importlib.util
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
sys.path[:0] = [str(HERE), str(ROOT / "tools")]

CACHED = 3
SCENES = ["updates", "alab"]  # run_benchmarks.py's groups
CALLS = [
    "synchronize",
    "unchanged",
    "move",
    "hide",
    "reload",
    "full rebuild",
    "cache",
    "cached frame",
    "back",
    "revisit",
]
# (module, function) pairs the calls reach their steps through, in the order they run.
STEPS = [
    ("proscenium_sync.api.bindings", "Bindings._require_binding"),
    ("proscenium_sync.source_access.stages", "BindingStages.reload"),
    ("proscenium_sync.synchronization", "synchronize"),
    ("proscenium_sync.synchronization", "cache"),
    ("proscenium_sync.binding_persistence.manifests", "read_manifest"),
    ("proscenium_sync.binding_persistence.binding_state", "read_generation"),
    ("proscenium_sync.source_access.stages", "BindingStages.acquire_evaluation_stage"),
    ("proscenium_sync.synchronization.evaluation", "source_state_diagnostics"),
    ("proscenium_sync.synchronization.evaluation", "evaluate_display_plans"),
    ("proscenium_sync.synchronization.evaluation", "_kept_chain"),
    ("proscenium_sync.core._core", "plan"),
    ("proscenium_sync.synchronization.partition_replacement", "partitions_to_replace"),
    ("proscenium_sync.core._core", "diff_plans"),
    ("proscenium_sync.synchronization.application", "prepare"),
    ("proscenium_sync.synchronization.local_updates", "prepare_updates"),
    ("proscenium_sync.synchronization.time_code_caching", "_varying_copies"),
    ("proscenium_sync.synchronization.time_code_keying", "key_time_codes"),
    ("proscenium_sync.synchronization.publication", "publish"),
    ("proscenium_sync.synchronization.local_updates", "apply_updates"),
    ("proscenium_sync.binding_persistence.manifests", "write_manifest"),
    ("proscenium_sync.binding_runtime.ownership", "set_manifest_entries"),
    ("proscenium_sync.binding_persistence.binding_state", "write_generation"),
    ("proscenium_sync.binding_runtime.held_plans", "HeldPlans.hold"),
    ("proscenium_sync.synchronization.preparation_resources", "remove_staging_and_clear_tracking"),
    ("proscenium_sync.synchronization.retirement", "retire"),
    ("proscenium_sync.synchronization.datablock_removal", "remove_unused"),
    ("proscenium_sync.synchronization.datablock_removal", "remove_datablocks_collecting_failures"),
    ("proscenium_sync.binding_persistence.binding_state", "write_last_attempt"),
    ("proscenium_sync.api.scene_source_selection", "mirror_after_publication"),
    ("proscenium_sync.api.bindings", "_push_undo"),
]


def run_once(blender: str, config: dict[str, Any], work: Path, timeout: float) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    (work / "config.json").write_text(json.dumps(config))
    child_args = ["--", "child", str(work / "config.json")]
    script = config.get("script", str(Path(__file__).resolve()))  # another measure script's child, if it names one
    if config.get("runtime", "binary") == "wheel":
        command = [sys.executable, script, *child_args]
    else:
        command = [
            blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            script,
            *child_args,
        ]
    env = {**os.environ, "BLENDER_USER_RESOURCES": str(work / "user")}
    with (work / "log.txt").open("w") as log:
        returncode = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=timeout).returncode
    result_path = work / "result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else None
    log_text = (work / "log.txt").read_text(errors="replace")
    return {"config": config, "returncode": returncode, "result": result, "log tail": log_text[-3000:]}


def _meshes_outside_instances(stage: Any, count: int) -> list[str]:
    """The paths of the stage's first meshes outside native instances and prototypes, in traversal order."""
    from pxr import Usd

    found = []
    for prim in Usd.PrimRange.Stage(stage, Usd.PrimDefaultPredicate):  # skips instance proxies
        if prim.GetTypeName() == "Mesh" and not prim.IsInPrototype():
            found.append(str(prim.GetPath()))
            if len(found) == count:
                return found
    raise RuntimeError(f"fewer than {count} meshes outside instances")


def child(config: dict[str, Any]) -> None:
    """One run, its result written where the config says."""
    import bpy

    sys.path.insert(0, str(ROOT / "src"))
    import memory
    from pxr import Gf, Usd, UsdGeom

    from proscenium_sync.api import bindings as api
    from proscenium_sync.binding_persistence import id_property_records, manifests

    bpy.ops.wm.read_factory_settings(use_empty=True)
    preferences: Any = bpy.context.preferences  # never None in a running Blender
    preferences.edit.use_global_undo = config.get("undo", True)
    api._undo_steps_enabled = lambda: True  # noqa: SLF001  # ty: ignore[invalid-assignment] - as with a window
    timings: dict[str, dict[str, float]] = {}
    pushes: list[int] = []  # each undo push's growth of the heap in use, in bytes

    def wrapped(label: str, call: Any) -> Any:
        @functools.wraps(call)
        def timed(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return call(*args, **kwargs)
            finally:
                entry = timings.setdefault(label, {"calls": 0, "s": 0.0})
                entry["calls"] += 1
                entry["s"] += time.perf_counter() - start

        return timed

    def measured_push(push: Any) -> Any:
        @functools.wraps(push)
        def pushed(message: str) -> None:
            before = memory.heap_in_use() or 0
            push(message)
            pushes.append((memory.heap_in_use() or 0) - before)

        return pushed

    for module_name, name in STEPS:
        owner: Any = importlib.import_module(module_name)
        *path, attribute = name.split(".")
        for part in path:
            owner = getattr(owner, part)
        call = getattr(owner, attribute)
        if name == "_push_undo":
            call = measured_push(call)
        setattr(owner, attribute, wrapped(attribute, call))

    scene: Any = bpy.context.scene
    view_layer: Any = bpy.context.view_layer
    at = config["time"]
    scene.frame_set(int(at))
    stage = Usd.Stage.Open(config["scene"])
    handle = api.BINDINGS.create_binding(scene, name="Profile")
    assert handle.attach(stage).is_success
    moved, hidden = _meshes_outside_instances(stage, 2)

    def move() -> Any:
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            UsdGeom.Xformable(stage.GetPrimAtPath(moved)).AddTranslateOp(opSuffix="phase_g").Set(Gf.Vec3d(0.01, 0, 0))
        return handle.synchronize(at)

    def hide() -> Any:
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            UsdGeom.Imageable(stage.GetPrimAtPath(hidden)).MakeInvisible()
        return handle.synchronize(at)

    def reload() -> Any:
        reloaded = handle.reload()
        assert reloaded.is_success, reloaded
        return handle.synchronize(at)

    def frame(frame_number: float) -> Any:
        def visit() -> None:
            scene.frame_set(int(frame_number))  # evaluates the depsgraph at the frame

        return visit

    calls = {
        "synchronize": lambda: handle.synchronize(at),
        "unchanged": lambda: handle.synchronize(at),
        "move": move,
        "hide": hide,
        "reload": reload,
        "full rebuild": lambda: handle.synchronize(at, full_rebuild=True),
        "cache": lambda: handle.cache([at + 1 + i for i in range(CACHED)]),
        "cached frame": frame(at + 1),
        "back": frame(at),
        "revisit": frame(at + 1),
    }
    steps: dict[str, Any] = {}
    for step in config["calls"]:
        timings.clear()
        pushes.clear()
        start = time.perf_counter()
        result = calls[step]()
        seconds = time.perf_counter() - start
        recorded: dict[str, Any] = {"s": seconds, "undo pushes bytes": list(pushes)}
        if result is not None:
            recorded |= {"state": str(result.state), "diagnostics": len(result.diagnostics)}
        recorded["timings"] = {label: dict(timing) for label, timing in timings.items()}  # before any later call
        gc.collect()
        recorded["heap after"] = memory.heap_in_use()
        start = time.perf_counter()
        view_layer.update()
        recorded["evaluate s"] = time.perf_counter() - start
        recorded["heap after evaluate"] = memory.heap_in_use()
        steps[step] = recorded
    destination = bpy.data.collections["Profile"]
    manifest = manifests.read_manifest(destination)
    held = api.BINDINGS.published_plans._plans_by_binding.get(handle.binding_id, {})  # noqa: SLF001
    held_count = len(held)
    del held
    gc.collect()
    before_release = memory.heap_in_use() or 0
    api.BINDINGS.published_plans.release(handle.binding_id)
    gc.collect()
    result = {
        "steps": steps,
        "moved": moved,
        "hidden": hidden,
        "held plans": held_count,
        "held plans bytes": before_release - (memory.heap_in_use() or 0),
        "manifest entries": len(manifest.record.entries)
        if isinstance(manifest, id_property_records.LoadedRecord)
        else 0,
        "objects": len(destination.all_objects),
        "file datablocks": sum(len(c) for c in (bpy.data.objects, bpy.data.meshes, bpy.data.actions)),
        "undo steps": preferences.edit.undo_steps,
        "blender version": bpy.app.version_string,
    }
    Path(config["result"]).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")


def _stats(values: list[float]) -> dict[str, float]:
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def _label(config: dict[str, Any]) -> str:
    """The scene's name, with its runtime and undo setting where they aren't the binary's with undo on."""
    runtime, undo = config.get("runtime", "binary"), config.get("undo", True)
    return config["scene name"] + (
        "" if (runtime, undo) == ("binary", True) else f", {runtime}, undo {'on' if undo else 'off'}"
    )


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """By scene and step: the step's, each timed function's, and the memory measures over the runs."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault(_label(run["config"]), []).append(run)
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
                key: first[key] for key in ("manifest entries", "objects", "file datablocks", "held plans", "moved")
            }
            entry["held plans bytes"] = _stats([r["held plans bytes"] for r in results])
            entry["steps"] = {}
            for step, data in first["steps"].items():
                functions = {
                    label: {
                        "calls": timing["calls"],
                        "s": _stats([r["steps"][step]["timings"].get(label, {"s": 0.0})["s"] for r in results]),
                    }
                    for label, timing in data["timings"].items()
                }
                entry["steps"][step] = {
                    "state": data.get("state", ""),
                    "s": _stats([r["steps"][step]["s"] for r in results]),
                    "undo push bytes": _stats([sum(r["steps"][step]["undo pushes bytes"]) for r in results]),
                    "pushes": len(data["undo pushes bytes"]),
                    "heap after": _stats([r["steps"][step]["heap after"] or 0 for r in results]),
                    "evaluate s": _stats([r["steps"][step]["evaluate s"] for r in results]),
                    "heap after evaluate": _stats([r["steps"][step]["heap after evaluate"] or 0 for r in results]),
                    "functions": functions,
                }
        summary[name] = entry
    return summary


def markdown(summary: dict[str, Any], setup: dict[str, Any]) -> str:
    def ms(stat: dict[str, float]) -> str:
        median, low, high = (stat[k] * 1000 for k in ("median", "min", "max"))
        return f"{median:,.1f} ({low:,.1f}-{high:,.1f})"

    def mb(stat: dict[str, float]) -> str:
        median, low, high = (stat[k] / 1e6 for k in ("median", "min", "max"))
        return f"{median:,.1f} ({low:,.1f}-{high:,.1f})"

    lines = ["# The product's synchronizations, step by step (M7 Phase G)", "", f"Setup: {json.dumps(setup)}", ""]
    for name, entry in summary.items():
        if not entry["runs"]:
            lines += [f"## {name}", "", f"failed: {entry['failed'][:1]}", ""]
            continue
        lines += [
            f"## {name}: {entry['objects']:,} objects, {entry['manifest entries']:,} manifest entries",
            "",
            f"Held plans at the end: {entry['held plans']}, freeing {mb(entry['held plans bytes'])} MB when released.",
            "",
            "| Step | Function | Calls | ms |",
            "|---|---|---|---|",
        ]
        labels = [n.split(".")[-1] for _, n in STEPS]
        for step, data in entry["steps"].items():
            lines.append(f"| **{step}** ({data['state']}) | | | **{ms(data['s'])}** |")
            for label in sorted(data["functions"], key=labels.index):
                function = data["functions"][label]
                lines.append(f"| | `{label}` | {function['calls']} | {ms(function['s'])} |")
        lines += [
            "",
            "| Step | Undo pushes | Push growth (MB) | Heap after (MB) | Evaluate (ms) | Heap after evaluate (MB) |",
            "|---|---|---|---|---|---|",
        ]
        for step, data in entry["steps"].items():
            lines.append(
                f"| {step} | {data['pushes']} | {mb(data['undo push bytes'])} | {mb(data['heap after'])} | "
                f"{ms(data['evaluate s'])} | {mb(data['heap after evaluate'])} |"
            )
        lines.append("")
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
    parser.add_argument("--undo", nargs="+", choices=["on", "off"], default=["on"], help="global undo settings")
    parser.add_argument("--runtimes", nargs="+", choices=["binary", "wheel"], default=["binary"])
    parser.add_argument("--no-full-rebuild", action="store_true", help="leave out the full rebuild")
    parser.add_argument("--timeout", type=float, default=3600.0, help="per run (s)")
    parser.add_argument("--out", type=Path, default=ROOT / "build/hydra-bridge/synchronization-profile")
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
    calls = [call for call in CALLS if not (args.no_full_rebuild and call == "full rebuild")]
    runs = []
    for repeat in range(args.repeats):
        for (name, scene), runtime, undo in itertools.product(found.items(), args.runtimes, args.undo):
            label = f"{name}-{runtime}-undo-{undo}-{repeat}"
            work = out / "work" / label
            config = {
                "scene name": name,
                "scene": scene["path"],
                "time": scene["time"],
                "runtime": runtime,
                "undo": undo == "on",
                "calls": calls,
                "work": str(work),
                "result": str(work / "result.json"),
            }
            result = run_once(args.blender, config, work, args.timeout)
            (out / "runs" / f"{label}.json").write_text(json.dumps(result) + "\n")
            print(f"{label}: {'ok' if result['returncode'] == 0 and result['result'] else 'failed'}", flush=True)
            runs.append(result)
    setup = {"environment": run.environment(args.blender), "cached": CACHED, "calls": calls}
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
