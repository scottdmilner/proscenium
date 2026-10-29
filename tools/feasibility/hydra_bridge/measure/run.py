"""Measurements of the Hydra prototype in fresh Blender processes, one per run: M1b's Phase E and M4's Phase C.

M1b compares it with Blender's USD importer; M4 adds its updates after each scenario's edit, and Phase D the
batched display (--representation batched, with --batch-minimum copies or more per batch), measured into its own
directory.

    uv run python tools/feasibility/hydra_bridge/measure/run.py [--scenes bespoke stress alab] [--repeats 5]
    uv run python tools/feasibility/hydra_bridge/measure/run.py --scenes updates alab --modes importer-matched \
        --scenarios all   # M4 Phase C: every update scenario, with the importer for the budgets
    uv run python tools/feasibility/hydra_bridge/measure/run.py --scenes updates alab --modes prototype interaction \
        --scenarios all --representation batched   # M4 Phase D: the batched display

Each run is sampled from outside with psutil (resident memory, CPU time, threads; on macOS also the physical
footprint) and aligned with the stage markers the child writes. Raw runs go to <out>/runs/, the summary to
<out>/summary.json and summary.md. Expects the module built by build.py in build/hydra-bridge/.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import psutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))

import alab_entry  # noqa: E402
import memory  # noqa: E402
import report  # noqa: E402
import scenarios  # noqa: E402
import stress  # noqa: E402

from blender_paths import find_blender  # noqa: E402

CASES = HERE.parent / "cases"
# The bespoke scenes the importer can read; malformed.usda is built to be rejected.
BESPOKE = ["subsets", "implicit", "instances", "edits", "untranslated", "bindings", "purposes", "primvars", "animation"]
MODES = ["importer-defaults", "prototype", "importer-matched", "importer-expanded"]
SMOKE = ["instances-100"]
ALAB_TIME = 1004.0  # the first of ALab's time codes


def scenes(groups: list[str], out: Path) -> dict[str, dict[str, Any]]:
    """Scene name -> path, time code, and how it was made."""
    found: dict[str, dict[str, Any]] = {}
    for group in groups:
        if group == "bespoke":
            for name in BESPOKE:
                found[name] = {"path": str(CASES / f"{name}.usda"), "time": 1.0, "group": group}
        elif group in ("stress", "smoke", "updates"):
            for name in {"stress": stress.STRESS, "smoke": SMOKE, "updates": stress.UPDATES}[group]:
                path, parameters = stress.generate(name, out / "scenes")
                found[name] = {
                    "path": str(path),
                    "time": stress.SCENES[name][1],
                    "group": group,
                    "parameters": parameters,
                }
        elif group in ("alab", "alab-instancers"):
            alab = os.environ.get("PROSCENIUM_ALAB_ROOT")
            if not alab:
                raise SystemExit(f"--scenes {group} needs PROSCENIUM_ALAB_ROOT (environment or .env)")
            stem = "alab_entry_measure" if group == "alab" else "alab_instancers_entry_measure"
            entry = out / "scenes" / f"{stem}.usda"
            entry.unlink(missing_ok=True)
            written = alab_entry.write(Path(alab) / "entry.usda", entry, point_instancers=group != "alab")
            (out / "scenes" / f"{stem}.json").write_text(json.dumps(written, indent=2) + "\n")
            found[group] = {
                "path": str(entry),
                "time": ALAB_TIME,
                "group": group,
                "parameters": {k: v for k, v in written.items() if k != "deactivated paths"},
                "point_instancers": group != "alab",
            }
        else:
            raise SystemExit(f"unknown scene group {group}")
    return found


def sample(process: psutil.Popen, interval: float, timeout: float) -> list[dict[str, Any]]:
    """Sample the child until it exits."""
    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        if time.monotonic() > deadline:
            process.kill()
            raise TimeoutError(f"run exceeded {timeout} s")
        try:
            with process.oneshot():
                cpu = process.cpu_times()
                record = {
                    "t": time.monotonic(),
                    "resident": process.memory_info().rss,
                    "cpu": cpu.user + cpu.system,
                    "threads": process.num_threads(),
                }
            footprint = memory.footprint(process.pid)
            if footprint is not None:
                record["footprint"] = footprint
        except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
            break
        samples.append(record)
        time.sleep(interval)
    return samples


def run_once(blender: str, scene: dict[str, Any], mode: str, args: argparse.Namespace, work: Path) -> dict[str, Any]:
    config = {
        "mode": mode,
        "scene": scene["path"],
        "time": scene["time"],
        "module_dir": str(args.module_dir),
        "markers": str(work / "markers.jsonl"),
        "result": str(work / "result.json"),
        "settle": args.settle,
        "work": str(work),
        "representation": args.representation,
        "batch_minimum": args.batch_minimum,
        "point_instancers": scene.get("point_instancers", False),
    }
    if mode.startswith("update:"):
        config["scenario"] = mode.removeprefix("update:")
    (work / "config.json").write_text(json.dumps(config))
    command = [
        blender,
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(HERE / "child.py"),
        "--",
        str(work / "config.json"),
    ]
    with (work / "log.txt").open("w") as log:
        process = psutil.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "BLENDER_USER_RESOURCES": str(work / "user")},
        )
        samples = sample(process, args.interval, args.timeout)
        returncode = process.wait()
    markers = (
        [json.loads(line) for line in (work / "markers.jsonl").read_text().splitlines()]
        if (work / "markers.jsonl").exists()
        else []
    )
    result = json.loads((work / "result.json").read_text()) if (work / "result.json").exists() else None
    log_text = (work / "log.txt").read_text(errors="replace")
    return {
        "mode": mode,
        "returncode": returncode,
        "samples": samples,
        "markers": markers,
        "result": result,
        "log tail": log_text[-4000:],
        "warnings": log_text.count("Warning"),
        "errors": log_text.count("Error"),
    }


def warmup_modes(modes: list[str]) -> list[str]:
    """One mode per side: the first importer mode, and the prototype's, which every update mode reads alike."""
    importer = [mode for mode in modes if mode.startswith("importer")][:1]
    prototype = [mode for mode in modes if not mode.startswith("importer")][:1]
    return importer + prototype


def environment(blender: str) -> dict[str, Any]:
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "blender": blender,
        "cpus": os.cpu_count(),
        "memory bytes": psutil.virtual_memory().total,
    }
    if sys.platform == "darwin":
        for key in ("hw.model", "machdep.cpu.brand_string"):
            info[key] = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True).stdout.strip()
        info["power"] = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout.strip()
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--scenes",
        nargs="+",
        default=["stress", "alab"],
        help="groups: bespoke, stress, alab, alab-instancers (its point instancers active, M4 Phase D), updates "
        "(M4 Phase C), smoke (one small scene, for CI)",
    )
    parser.add_argument("--only", nargs="+", help="scene names within the groups")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="unrecorded runs per scene before its repeats, of each side's first mode, for the file cache and loader",
    )
    parser.add_argument(
        "--modes",
        nargs="*",
        default=MODES,
        choices=[*MODES, "interaction", "ownership"],
        help="synchronization modes; interaction and ownership (M4 Phase C) time the interaction functions, or "
        "the first ownership lookup after an undo, after one",
    )
    parser.add_argument(
        "--scenarios",
        nargs="*",
        default=[],
        choices=[*scenarios.SCENARIOS, "all"],
        help="M4 Phase C update scenarios, each run as its own mode (update:<scenario>) after the modes",
    )
    parser.add_argument("--interval", type=float, default=0.01, help="sampling interval (s)")
    parser.add_argument("--settle", type=float, default=0.5, help="length of each rest window (s)")
    parser.add_argument("--timeout", type=float, default=3600.0, help="per run (s)")
    parser.add_argument(
        "--representation",
        choices=["objects", "batched"],
        default="objects",
        help="the prototype's display: the baseline's objects, or Phase D's batched display",
    )
    parser.add_argument(
        "--batch-minimum", type=int, default=2, help="the batched display's smallest group that becomes a batch"
    )
    parser.add_argument("--out", type=Path, help="default: build/hydra-bridge/measure, or measure-batched")
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
    default = "measure" if args.representation == "objects" else "measure-batched"
    out: Path = (args.out or ROOT / "build/hydra-bridge" / default).resolve()
    (out / "runs").mkdir(parents=True, exist_ok=True)
    found = scenes(args.scenes, out)
    chosen = list(scenarios.SCENARIOS) if "all" in args.scenarios else args.scenarios
    modes = [*args.modes, *(f"update:{scenario}" for scenario in chosen)]
    if args.only:
        found = {name: scene for name, scene in found.items() if name in args.only}
    failed = []
    warmups = warmup_modes(modes)
    for name, scene in found.items():
        for warmup in range(args.warmup):
            for mode in warmups:
                with tempfile.TemporaryDirectory(prefix="hydra-measure-") as tmp:
                    run = run_once(args.blender, scene, mode, args, Path(tmp))
                status = "ok" if run["returncode"] == 0 and run["result"] else f"FAILED (exit {run['returncode']})"
                print(f"{name} {mode} warmup #{warmup}: {status} (not recorded)", flush=True)
        for repeat in range(args.repeats):
            for mode in modes:
                with tempfile.TemporaryDirectory(prefix="hydra-measure-") as tmp:
                    run = run_once(args.blender, scene, mode, args, Path(tmp))
                run.update(scene=name, repeat=repeat)
                (out / "runs" / f"{name}-{mode.replace(':', '_')}-{repeat}.json").write_text(json.dumps(run) + "\n")
                status = "ok" if run["returncode"] == 0 and run["result"] else f"FAILED (exit {run['returncode']})"
                if status != "ok":
                    failed.append(f"{name} {mode} {repeat}")
                    print(run["log tail"][-2000:])
                print(f"{name} {mode} #{repeat}: {status}", flush=True)
    # The summary covers every scene measured into this directory, so one group can be rerun on its own.
    measured_path = out / "scenes.json"
    measured = json.loads(measured_path.read_text()) if measured_path.exists() else {}
    measured.update(found)
    measured_path.write_text(json.dumps(measured, indent=2) + "\n")
    setup = {**environment(args.blender), "warmup": f"{args.warmup} unrecorded run(s) per scene of {warmups}"}
    setup["representation"] = args.representation
    if args.representation == "batched":
        setup["batch minimum"] = args.batch_minimum
    summary = report.summarize(out / "runs", measured, setup)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "summary.md").write_text(report.markdown(summary))
    print(f"summary: {out / 'summary.md'}")
    if failed:
        print("failed runs: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
