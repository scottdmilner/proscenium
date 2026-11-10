"""M4 Phase E (E4): a cached display of meshes whose topology changes every frame, a mesh per sample.

    uv run python tools/feasibility/hydra_bridge/measure/topology_caches.py [--out build/hydra-bridge/topology-caches]

Runs in the bpy wheel, in one process, on the generated `topology` stress scene (stress.py): 355 grids, each
changing its side every frame over 24 frames. A cached display (cached.py) is built at the first frame and
follows the scene, with each later frame set in turn, so each synchronizes once. Each frame times the
synchronization by stage, the frame's evaluation, and an undo push with global undo on, with the process
footprint around the push. Then every frame is played back, a sample of objects is checked against fresh plans,
and the file is saved uncompressed. Writes <out>/meshes.json; nothing is written outside <out>.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(HERE), str(HERE.parent)]

import bpy  # noqa: E402
import cached  # noqa: E402
import numpy  # noqa: E402
import stress  # noqa: E402
from memory import footprint, heap_in_use  # noqa: E402
from pxr import Usd  # noqa: E402

FIRST, LAST = stress.FRAMES
CHECKED = 5  # objects checked against fresh plans at every frame


def megabytes(value: int | None) -> float | None:
    return None if value is None else round(value / 2**20, 1)


def median(values: list[float]) -> float:
    return round(statistics.median(values), 4)


def evaluated(obj: bpy.types.Object) -> tuple[numpy.ndarray, numpy.ndarray]:
    """An object's evaluated positions and corner vertices."""
    geometry = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
    mesh: Any = geometry.mesh
    positions = numpy.empty(len(mesh.vertices) * 3, numpy.float32)
    mesh.vertices.foreach_get("co", positions)
    corners = numpy.empty(len(mesh.loops), numpy.int32)
    mesh.attributes[".corner_vert"].data.foreach_get("value", corners)
    return positions, corners


def main() -> int:  # noqa: PLR0915 - one run, start to end
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "build/hydra-bridge/topology-caches")
    parser.add_argument("--module-dir", type=Path, default=ROOT / "build/hydra-bridge")
    args = parser.parse_args()
    out: Path = args.out.resolve()
    work = out / "work-meshes"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    scene_path, parameters = stress.generate("topology", out / "scenes")
    sys.path.insert(0, str(args.module_dir))
    import _hydra_bridge as native  # ty: ignore[unresolved-import] - built into build/hydra-bridge

    bpy.ops.wm.read_factory_settings(use_empty=True)
    preferences: Any = bpy.context.preferences
    preferences.edit.use_global_undo = True
    scene: Any = bpy.context.scene
    scene.frame_start, scene.frame_end = FIRST, LAST
    scene.frame_set(FIRST)
    stage = Usd.Stage.Open(str(scene_path))
    collection = bpy.data.collections.new("Cached")
    scene.collection.children.link(collection)
    process = os.getpid()
    memory = {"start heap MB": megabytes(heap_in_use())}
    clock = time.perf_counter()
    display = cached.CachedDisplay(native, stage, collection, float(FIRST))
    built = time.perf_counter() - clock
    view_layer: Any = bpy.context.view_layer  # never None in a running Blender
    view_layer.update()
    memory["built heap MB"] = megabytes(heap_in_use())
    handler = display.install_frame_change_handler(scene)
    bpy.ops.ed.undo_push(message="built")
    steps: list[dict[str, Any]] = []
    for frame in range(FIRST + 1, LAST + 1):
        count = len(display.synchronized)
        clock = time.perf_counter()
        scene.frame_set(frame)
        step: dict[str, Any] = {"frame": frame, "frame_set s": time.perf_counter() - clock}
        (synchronization,) = display.synchronized[count:]
        step |= {f"{stage} s": seconds for stage, seconds in synchronization.seconds.items()}
        step["written"] = synchronization.written
        before = footprint(process)
        clock = time.perf_counter()
        bpy.ops.ed.undo_push(message=f"frame {frame}")
        step["undo push s"] = time.perf_counter() - clock
        after = footprint(process)
        step["undo push footprint MB"] = megabytes(None if before is None or after is None else after - before)
        steps.append(step)
        print(json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in step.items()}), flush=True)
    bpy.app.handlers.frame_change_pre.remove(handler)
    memory["filled heap MB"] = megabytes(heap_in_use())

    playback = []
    for frame in range(FIRST, LAST + 1):
        clock = time.perf_counter()
        scene.frame_set(frame)
        playback.append(time.perf_counter() - clock)
    checked = sorted(display.objects)[:CHECKED]
    mismatched = []
    for frame in range(FIRST, LAST + 1):
        bridge = native.Bridge(stage)
        plan = native.build_plan(bridge.capture(float(frame)))
        bridge.release()
        by_source = {r["source"]: r for r in plan.objects}
        scene.frame_set(frame)
        for key in checked:
            mesh = plan.meshes_at([by_source[key[0]]["mesh"]])[0]
            positions, corners = evaluated(display.objects[key])
            expected = numpy.array(mesh["positions"], numpy.float32).ravel()
            same = positions.shape == expected.shape and numpy.array_equal(positions, expected)
            if not same or not numpy.array_equal(corners, numpy.array(mesh["corner_verts"], numpy.int32)):
                mismatched.append(f"{key[0]}@{frame}")
    blend = work / "final.blend"
    clock = time.perf_counter()
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=False)
    saved = time.perf_counter() - clock
    display.release()

    per_frame = ["frame_set s", "capture s", "planning s", "diff s", "cache s", "undo push s"]
    result = {
        "runtime": f"bpy wheel {bpy.app.version_string}, in-process",
        "scene": parameters,
        "build s": round(built, 2),
        "per frame median": {key: median([step[key] for step in steps]) for key in per_frame},
        "per frame max": {key: round(max(step[key] for step in steps), 4) for key in per_frame},
        "cache s, first and last tenth": [
            median([s["cache s"] for s in steps[: max(1, len(steps) // 10)]]),
            median([s["cache s"] for s in steps[-max(1, len(steps) // 10) :]]),
        ],
        "undo push footprint MB median": median([s["undo push footprint MB"] or 0.0 for s in steps]),
        "memory": memory,
        "playback (revisit) s": {"median": median(playback), "max": round(max(playback), 4)},
        "objects checked at every frame": len(checked),
        "mismatched": mismatched,
        "blend MB": megabytes(blend.stat().st_size),
        "save s": round(saved, 2),
        "frames": steps,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "meshes.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "frames"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
