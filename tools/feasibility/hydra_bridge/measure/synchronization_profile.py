"""M5 Phase F (F3): the product's synchronization and cache call against the stub, step by step, in the Blender binary.

    uv run python tools/feasibility/hydra_bridge/measure/synchronization_profile.py [--scenes updates alab] \
        [--repeats 3] [--undo on off] [--runtimes binary wheel]

Each run makes a binding through the API (proscenium.api.bindings), attaches the scene's stage, and synchronizes at
its time code, then synchronizes again at it, a full rebuild that retires the first generation, then caches CACHED
later time codes. Global undo is on, or as --undo says (M6 Phase F, F5), and the API pushes its step as it would with a
window (its _pushes_undo patched true, since background mode pushes none). --runtimes runs it in the bpy wheel too.
Each step of the transaction is timed by wrapping the module function it calls (STEPS), so a time includes the steps
it calls; a step called more than once is summed, with its calls counted. The stub application layer makes an object
and a bounds mesh for each drawn copy, not M7's display, so this measures the work around it. Raw runs go to
<out>/runs/, the summary to <out>/summary.json and summary.md.
"""

from __future__ import annotations

import argparse
import functools
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
SCENES = ["updates", "alab"]  # run.py's groups
# (module, function) pairs the transaction and cache call reach their steps through, in the order they run.
STEPS = [
    ("proscenium.api.bindings", "Bindings._found"),
    ("proscenium.synchronization.transaction", "synchronize"),
    ("proscenium.synchronization.caching", "cache"),
    ("proscenium.binding.persistence.manifests", "read_manifest"),
    ("proscenium.binding.persistence.binding_state", "read_generation"),
    ("proscenium.binding.source_access.stages", "BindingStages.acquire"),
    ("proscenium.synchronization.evaluation", "source_state"),
    ("proscenium.synchronization.evaluation", "plans"),
    ("proscenium.synchronization.application", "prepare"),
    ("proscenium.synchronization.application", "key_time_codes"),
    ("proscenium.synchronization.publication", "publish"),
    ("proscenium.binding.persistence.manifests", "write_manifest"),
    ("proscenium.binding.runtime.ownership", "set_manifest_entries"),
    ("proscenium.binding.persistence.binding_state", "write_generation"),
    ("proscenium.synchronization.prepared_work", "remove_staging"),
    ("proscenium.synchronization.retirement", "retire"),
    ("proscenium.synchronization.removal", "remove_unused"),
    ("bpy.data", "user_map"),
    ("proscenium.synchronization.removal", "_batch_remove"),
    ("proscenium.binding.persistence.binding_state", "write_last_attempt"),
    ("proscenium.api.bindings", "_push_undo"),
]


def run_once(blender: str, config: dict[str, Any], work: Path, timeout: float) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    (work / "config.json").write_text(json.dumps(config))
    child_args = ["--", "child", str(work / "config.json")]
    if config.get("runtime", "binary") == "wheel":
        command = [sys.executable, str(Path(__file__).resolve()), *child_args]
    else:
        command = [
            blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(Path(__file__).resolve()),
            *child_args,
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

    sys.path.insert(0, str(ROOT / "src"))
    from pxr import Usd

    from proscenium.api import bindings as api
    from proscenium.binding.persistence import manifests, records

    bpy.ops.wm.read_factory_settings(use_empty=True)
    preferences: Any = bpy.context.preferences  # never None in a running Blender
    preferences.edit.use_global_undo = config.get("undo", True)
    api._pushes_undo = lambda: True  # noqa: SLF001  # ty: ignore[invalid-assignment] - as with a window
    timings: dict[str, dict[str, float]] = {}

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

    for module_name, name in STEPS:
        owner: Any = bpy.data if module_name == "bpy.data" else importlib.import_module(module_name)
        *path, attribute = name.split(".")
        for part in path:
            owner = getattr(owner, part)
        if module_name == "bpy.data":  # bpy.data's functions can't be replaced, so the removal's use of it is
            removal: Any = importlib.import_module("proscenium.synchronization.removal")
            removal.bpy = _Bpy(bpy, wrapped("user_map", bpy.data.user_map))
            continue
        setattr(owner, attribute, wrapped(name.split(".")[-1], getattr(owner, attribute)))

    scene: Any = bpy.context.scene
    stage = Usd.Stage.Open(config["scene"])
    handle = api.BINDINGS.create_binding(scene, name="Profile")
    assert handle.attach(stage).is_success
    at = config["time"]
    steps: dict[str, Any] = {}
    for step, call in (
        ("synchronize", lambda: handle.synchronize(at)),
        ("synchronize again", lambda: handle.synchronize(at)),
        ("cache", lambda: handle.cache([at + 1 + i for i in range(CACHED)])),
    ):
        timings.clear()
        start = time.perf_counter()
        result = call()
        seconds = time.perf_counter() - start
        steps[step] = {"s": seconds, "state": str(result.state), "diagnostics": len(result.diagnostics)}
        steps[step]["timings"] = {label: dict(timing) for label, timing in timings.items()}  # before any later call
    destination = bpy.data.collections["Profile"]
    manifest = manifests.read_manifest(destination)
    result = {
        "steps": steps,
        "manifest entries": len(manifest.record.entries) if isinstance(manifest, records.Loaded) else 0,
        "objects": len(destination.all_objects),
        "file datablocks": sum(len(c) for c in (bpy.data.objects, bpy.data.meshes, bpy.data.actions)),
        "blender version": bpy.app.version_string,
    }
    Path(config["result"]).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")


class _Bpy:
    """bpy as removal.py reaches it, with bpy.data.user_map timed."""

    def __init__(self, bpy: Any, user_map: Any) -> None:
        self._bpy = bpy
        self.data = _Data(bpy.data, user_map)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._bpy, name)


class _Data:
    def __init__(self, data: Any, user_map: Any) -> None:
        self._data = data
        self.user_map = user_map

    def __getattr__(self, name: str) -> Any:
        return getattr(self._data, name)


def _stats(values: list[float]) -> dict[str, float]:
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def _label(config: dict[str, Any]) -> str:
    """The scene's name, with its runtime and undo setting where they aren't the binary's with undo on."""
    runtime, undo = config.get("runtime", "binary"), config.get("undo", True)
    return config["scene name"] + (
        "" if (runtime, undo) == ("binary", True) else f", {runtime}, undo {'on' if undo else 'off'}"
    )


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """By scene and step: the step's and each timed function's seconds over the runs, with the first run's calls."""
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
            entry |= {"manifest entries": first["manifest entries"], "objects": first["objects"], "steps": {}}
            for step, data in first["steps"].items():
                functions = {
                    label: {
                        "calls": timing["calls"],
                        "s": _stats([r["steps"][step]["timings"].get(label, {"s": 0.0})["s"] for r in results]),
                    }
                    for label, timing in data["timings"].items()
                }
                entry["steps"][step] = {
                    "state": data["state"],
                    "s": _stats([r["steps"][step]["s"] for r in results]),
                    "functions": functions,
                }
        summary[name] = entry
    return summary


def markdown(summary: dict[str, Any], setup: dict[str, Any]) -> str:
    def cell(stat: dict[str, float]) -> str:
        median, low, high = (stat[k] * 1000 for k in ("median", "min", "max"))
        return f"{median:,.1f} ({low:,.1f}-{high:,.1f})"

    lines = ["# The product's synchronization, step by step (M5 Phase F, F3)", "", f"Setup: {json.dumps(setup)}", ""]
    for name, entry in summary.items():
        if not entry["runs"]:
            lines += [f"## {name}", "", f"failed: {entry['failed'][:1]}", ""]
            continue
        lines += [
            f"## {name}: {entry['objects']:,} objects, {entry['manifest entries']:,} manifest entries",
            "",
            "| Step | Function | Calls | ms |",
            "|---|---|---|---|",
        ]
        for step, data in entry["steps"].items():
            lines.append(f"| **{step}** ({data['state']}) | | | **{cell(data['s'])}** |")
            labels = [n.split(".")[-1] for _, n in STEPS]
            for label in sorted(data["functions"], key=labels.index):
                function = data["functions"][label]
                lines.append(f"| | `{label}` | {function['calls']} | {cell(function['s'])} |")
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
    parser.add_argument("--exclude", nargs="*", default=[], help="scenes of those groups to leave out")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--undo", nargs="+", choices=["on", "off"], default=["on"], help="global undo settings")
    parser.add_argument("--runtimes", nargs="+", choices=["binary", "wheel"], default=["binary"])
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
                "work": str(work),
                "result": str(work / "result.json"),
            }
            result = run_once(args.blender, config, work, args.timeout)
            (out / "runs" / f"{label}.json").write_text(json.dumps(result) + "\n")
            print(f"{label}: {'ok' if result['returncode'] == 0 and result['result'] else 'failed'}", flush=True)
            runs.append(result)
    setup = {"environment": run.environment(args.blender), "cached": CACHED}
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
