"""M4 Phase E (E7): playback of each time-sampled representation, in fresh Blender binary processes, one per run.

    uv run python tools/feasibility/hydra_bridge/measure/playback.py [--scenes alab animation scatter] \
        [--approaches snapshots attributes sequence] [--representations objects batched] [--repeats 3] [--check]

Each run builds the display at the scene's first frame, sets each later frame in turn (its first visit), then
every frame again (a revisit), and saves the .blend uncompressed. The approaches:
- snapshots: E2's per-time-code snapshots, with moves; every visit is a step through the update path.
- attributes: the cached display (E3 to E5), its meshes' samples as attributes.
- sequence: the cached display, its meshes' samples in a USD file read by Mesh Sequence Cache modifiers (E6).

Batched, snapshots use Phase D's batched display and the cached display its batches (E5), both at
--batch-minimum. The sequence caches refuse a mesh Blender's reader can't give back as the display holds it, as
some of ALab's are; --lossy writes them anyway (a FLOAT2 on points as a vertex float2, a display color without its
opacity), for their cost only. With --check, each cached display is also checked against fresh plans at three
frames (tests/isolated/bodies/caching.py), after the timings. Raw runs go to <out>/runs/, the summary to
<out>/summary.json and summary.md. Expects the module built by build.py in build/hydra-bridge/.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apply import Layer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
# The bridge first: this directory has measurements named as its modules (mesh_caches.py).
sys.path[:0] = [str(HERE.parent), str(HERE), str(ROOT / "tools")]

APPROACHES = ["snapshots", "attributes", "sequence"]
REPRESENTATIONS = ["objects", "batched"]
SCENES = ["alab", "alab-objects", "animation", "scatter"]  # and stress.py's groups-N, or a USD file's path
ALAB_FRAMES = (1004, 1057)  # ALab's range


def scenes(names: list[str], out: Path) -> dict[str, dict[str, Any]]:
    """Scene name -> path, frame range, and how it was made."""
    import alab_entry
    import stress

    found: dict[str, dict[str, Any]] = {}
    for name in names:
        if name in ("alab", "alab-objects"):
            alab = os.environ.get("PROSCENIUM_ALAB_ROOT")
            if not alab:
                raise SystemExit("--scenes alab needs PROSCENIUM_ALAB_ROOT (environment or .env)")
            entry = out / "scenes" / f"{name}_playback.usda"
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.unlink(missing_ok=True)
            # alab-objects: ALab with its point instancers deactivated, as M1b measured it.
            written = alab_entry.write(Path(alab) / "entry.usda", entry, point_instancers=name == "alab")
            parameters = {k: v for k, v in written.items() if k != "deactivated paths"}
            found[name] = {"path": str(entry), "frames": ALAB_FRAMES, "parameters": parameters}
        elif name.endswith((".usd", ".usda", ".usdc")):
            from pxr import Usd

            stage = Usd.Stage.Open(name)
            frames = (int(stage.GetStartTimeCode()), int(stage.GetEndTimeCode()))
            found[Path(name).stem] = {"path": name, "frames": frames, "parameters": {"file": name}}
        else:
            generated = {"animation": "animation", "scatter": "scatter-10000"}.get(name, name)
            path, parameters = stress.generate(generated, out / "scenes")
            found[name] = {"path": str(path), "frames": stress.FRAMES, "parameters": parameters}
    return found


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

    sys.path[:0] = [config["module_dir"], str(ROOT)]
    import _hydra_bridge as native  # ty: ignore[unresolved-import] - built into build/hydra-bridge
    import cached
    import memory
    import snapshots
    from pxr import Usd

    bpy.ops.wm.read_factory_settings(use_empty=True)
    work = Path(config["work"])
    first, last = config["frames"]
    scene: Any = bpy.context.scene
    scene.frame_start, scene.frame_end = first, last
    scene.frame_set(first)
    stage = Usd.Stage.Open(config["scene"])
    collection = bpy.data.collections.new("Playback")
    scene.collection.children.link(collection)
    approach, batched = config["approach"], config["representation"] == "batched"
    minimum = config["batch_minimum"]
    if config["lossy"]:
        _lossy()
    mb = lambda value: None if value is None else round(value / 2**20, 1)  # noqa: E731
    result: dict[str, Any] = {"heap MB": {"before": mb(memory.heap_in_use())}}
    start = time.perf_counter()
    if approach == "snapshots":
        display: Any = snapshots.Snapshots(
            native, stage, collection, float(first), "batched" if batched else "objects", moves=True, minimum=minimum
        )
        synchronize = display.step
    else:
        path = str(work / "cache.usdc") if approach == "sequence" else None
        display = cached.CachedDisplay(
            native, stage, collection, float(first), minimum=minimum if batched else None, sequence=path
        )
        synchronize = display.synchronize
    result["build s"] = time.perf_counter() - start
    result["heap MB"]["built"] = mb(memory.heap_in_use())
    errors: list[str] = []
    stages: list[dict[str, float]] = []

    def on_frame(changed: Any, _depsgraph: Any = None) -> None:
        try:
            step = synchronize(float(changed.frame_current))
        except Exception as error:
            errors.append(f"{changed.frame_current}: {type(error).__name__}: {error}")
            raise
        if step is not None:
            stages.append(dict(step.seconds))

    bpy.app.handlers.frame_change_pre.append(on_frame)
    first_visits, revisits = [], []
    for frame in range(first + 1, last + 1):
        start = time.perf_counter()
        scene.frame_set(frame)
        first_visits.append(time.perf_counter() - start)
        if errors:
            break
    result["heap MB"]["filled"] = mb(memory.heap_in_use())
    result["footprint MB"] = mb(memory.footprint(os.getpid()))
    visited = len(stages)
    for frame in range(first, last + 1) if not errors else ():
        start = time.perf_counter()
        scene.frame_set(frame)
        revisits.append(time.perf_counter() - start)
    result |= {
        "errors": errors,
        "first visit s": first_visits,
        "stages": stages[:visited],
        "revisit s": revisits,
        "revisit synchronizations": len(stages) - visited,
        "objects": len(collection.all_objects),
    }
    if config["check"] and approach != "snapshots" and not errors:
        from tests.isolated.bodies import caching

        result["mismatches"] = {}
        for frame in sorted({min(first + 1, last), (first + last) // 2, last}):  # a static scene's one frame
            scene.frame_set(frame)
            result["mismatches"][frame] = caching._mismatches(native, stage, display, float(frame))  # noqa: SLF001
    bpy.app.handlers.frame_change_pre.remove(on_frame)
    if approach == "sequence":
        start = time.perf_counter()
        meshes: Any = display.meshes  # sequence_caches.SequenceCaches
        meshes.save()
        result["usd save s"] = time.perf_counter() - start
        result["usd MB"] = mb((work / "cache.usdc").stat().st_size)
    blend = work / "playback.blend"
    start = time.perf_counter()
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=False)
    result["blend save s"] = time.perf_counter() - start
    result["blend MB"] = mb(blend.stat().st_size)
    blend.unlink()
    display.release()
    result["blender version"] = bpy.app.version_string
    Path(config["result"]).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")


def _lossy() -> None:
    """Have the sequence caches write what Blender's reader gives back otherwise, for measurement only."""
    import numpy
    import sequence_caches
    from pxr import Sdf, Vt

    exact = sequence_caches._primvar  # noqa: SLF001

    def lossy(layer: Layer) -> tuple[sequence_caches.PrimvarKind, Any]:
        if layer.data_type == "FLOAT2" and layer.domain == "POINT":
            return (Sdf.ValueTypeNames.Float2Array, "vertex"), Vt.Vec2fArray.FromNumpy(layer.values.reshape(-1, 2))
        if layer.name == sequence_caches.DISPLAY_COLOR:
            rgb = numpy.ascontiguousarray(layer.values.reshape(-1, 4)[:, :3])
            interpolation = sequence_caches.INTERPOLATIONS[layer.domain]
            return (Sdf.ValueTypeNames.Color3fArray, interpolation), Vt.Vec3fArray.FromNumpy(rgb)
        return exact(layer)

    sequence_caches._primvar = lossy  # noqa: SLF001  # ty: ignore[invalid-assignment] - a patch, for measurement


def _stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {"median": statistics.median(values), "min": min(values), "max": max(values)}


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """By scene, approach, and representation: each measure's median over the runs, with its range."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        config = run["config"]
        grouped.setdefault(f"{config['scene name']} {config['approach']} {config['representation']}", []).append(run)
    summary: dict[str, Any] = {}
    for name, group in grouped.items():
        results = [run["result"] for run in group if run["result"] and not run["result"]["errors"]]
        failed = [run["result"]["errors"][:1] if run["result"] else run["log tail"][-300:] for run in group]
        entry: dict[str, Any] = {"runs": len(results), "failed": [f for f in failed if f] if not results else []}
        if results:
            entry |= {
                "build s": _stats([r["build s"] for r in results]),
                "first visit s": _stats([statistics.median(r["first visit s"]) for r in results if r["first visit s"]]),
                "first visit max s": _stats([max(r["first visit s"]) for r in results if r["first visit s"]]),
                "revisit s": _stats([statistics.median(r["revisit s"]) for r in results]),
                "heap built MB": _stats([r["heap MB"]["built"] - r["heap MB"]["before"] for r in results]),
                "heap filled MB": _stats([r["heap MB"]["filled"] - r["heap MB"]["before"] for r in results]),
                "blend MB": _stats([r["blend MB"] for r in results]),
                "usd MB": _stats([r["usd MB"] for r in results if "usd MB" in r]),
                "usd save s": _stats([r["usd save s"] for r in results if "usd save s" in r]),
                "objects": results[0]["objects"],
                "revisit synchronizations": max(r["revisit synchronizations"] for r in results),
                "mismatches": [
                    {frame: len(found) for frame, found in r["mismatches"].items()}
                    for r in results
                    if "mismatches" in r
                ],
            }
        summary[name] = entry
    return summary


def markdown(summary: dict[str, Any], setup: dict[str, Any]) -> str:
    def cell(stat: dict[str, float] | None, scale: float = 1.0, digits: int = 2) -> str:
        if stat is None:
            return "-"
        median, low, high = (stat[k] * scale for k in ("median", "min", "max"))
        return f"{median:.{digits}f} ({low:.{digits}f}-{high:.{digits}f})"

    lines = [
        "# Playback of the time-sampled representations (M4 Phase E, E7)",
        "",
        f"Setup: {json.dumps(setup)}",
        "",
        "Medians over the runs, with their range; a frame's first visit and a revisit are each run's median.",
        "",
        "| Scene, approach, representation | Runs | Build s | First visit s | Revisit ms | Heap built MB | "
        "Heap filled MB | .blend MB | USD MB | Objects |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, entry in summary.items():
        if not entry["runs"]:
            lines.append(f"| {name} | 0 | failed: {entry['failed'][:1]} | | | | | | | |")
            continue
        lines.append(
            f"| {name} | {entry['runs']} | {cell(entry['build s'])} | {cell(entry['first visit s'], digits=3)} | "
            f"{cell(entry['revisit s'], 1000, 1)} | {cell(entry['heap built MB'], digits=0)} | "
            f"{cell(entry['heap filled MB'], digits=0)} | {cell(entry['blend MB'], digits=0)} | "
            f"{cell(entry['usd MB'], digits=0)} | {entry['objects']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    from blender_paths import find_blender

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenes", nargs="+", default=SCENES, help=f"{SCENES}, groups-N, or USD files' paths")
    parser.add_argument("--frames", type=int, help="visit at most this many frames after the first")
    parser.add_argument("--approaches", nargs="+", default=APPROACHES, choices=APPROACHES)
    parser.add_argument("--representations", nargs="+", default=REPRESENTATIONS, choices=REPRESENTATIONS)
    parser.add_argument("--batch-minimum", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--lossy", action="store_true", help="the sequence caches write what the reader alters")
    parser.add_argument("--check", action="store_true", help="check each cached display against fresh plans")
    parser.add_argument("--timeout", type=float, default=3600.0, help="per run (s)")
    parser.add_argument("--out", type=Path, default=ROOT / "build/hydra-bridge/playback")
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
    found = scenes(args.scenes, out)
    runs = []
    for name, scene in found.items():
        if args.frames is not None:
            first, last = scene["frames"]
            scene["frames"] = (first, min(last, first + args.frames))
        for repeat in range(args.repeats):
            for approach in args.approaches:
                for representation in args.representations:
                    label = f"{name}-{approach}-{representation}-{repeat}"
                    work = out / "work" / label
                    config = {
                        "scene name": name,
                        "scene": scene["path"],
                        "frames": scene["frames"],
                        "approach": approach,
                        "representation": representation,
                        "batch_minimum": args.batch_minimum,
                        "lossy": args.lossy,
                        "check": args.check,
                        "module_dir": str(args.module_dir.resolve()),
                        "work": str(work),
                        "result": str(work / "result.json"),
                    }
                    run = run_once(args.blender, config, work, args.timeout)
                    (out / "runs" / f"{label}.json").write_text(json.dumps(run) + "\n")
                    errors = run["result"]["errors"] if run["result"] else ["no result"]
                    print(f"{label}: {'ok' if run['returncode'] == 0 and not errors else errors[:1]}", flush=True)
                    runs.append(run)
    setup = {
        "blender": args.blender,
        "batch minimum": args.batch_minimum,
        "lossy": args.lossy,
        "scenes": {name: {"frames": s["frames"], **s["parameters"]} for name, s in found.items()},
    }
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
