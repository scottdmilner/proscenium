"""M7 Phase B (B4): the two candidate fixes for retirement after an undo push, measured in the Blender binary.

    uv run python tools/feasibility/hydra_bridge/measure/retirement_after_undo_push.py [--scenes updates alab] \
        [--exclude updates-100] [--repeats 3]

Each run makes a binding through the API, attaches the scene's stage, synchronizes, and synchronizes again, a full
rebuild that retires the first generation, with the API pushing its undo step as with a window (M6 Phase F, F5). The
second synchronization's retirement is wrapped: before it runs, the run counts the obsolete datablocks bpy.data.user_map
names a Scene user of, then times each candidate in turn,

- scene users: reading each such object's users_collection, to find a Scene user with no collection of its own linking
  it, which reads only (lifecycle.md's external users would need more than this to tell a real reference apart);
- resync: ViewLayer.update() on each scene's view layers, after which it counts the Scene users again;

and then lets retirement run, recording how long it took and how many objects, meshes, and actions the file holds
after, against the generation's. Raw runs go to <out>/runs/, the summary to <out>/summary.json and summary.md.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(HERE), str(ROOT / "tools")]


def _scene_used(bpy: Any, datablocks: list[Any]) -> list[Any]:
    """The datablocks bpy.data.user_map names a Scene user of."""
    users = bpy.data.user_map(subset=datablocks)
    return [d for d in datablocks if any(isinstance(u, bpy.types.Scene) for u in users[d])]


def child(config: dict[str, Any]) -> None:
    """One run, its result written where the config says."""
    import bpy

    sys.path.insert(0, str(ROOT / "src"))
    from pxr import Usd

    from proscenium_sync.api import bindings as api
    from proscenium_sync.results import ResultState
    from proscenium_sync.synchronization import retirement

    bpy.ops.wm.read_factory_settings(use_empty=True)
    preferences: Any = bpy.context.preferences  # never None in a running Blender
    preferences.edit.use_global_undo = True
    api._undo_steps_enabled = lambda: True  # noqa: SLF001  # ty: ignore[invalid-assignment] - as with a window
    measured: dict[str, Any] = {}
    retire = retirement.retire

    def measuring(binding_id: Any, obsolete: Any, operation: Any) -> Any:
        if not measured.get("armed"):
            return retire(binding_id, obsolete, operation)
        datablocks = [e.datablock for e in obsolete.values() if e.datablock is not None]
        stale = _scene_used(bpy, datablocks)
        start = time.perf_counter()
        unlinked = [d for d in stale if isinstance(d, bpy.types.Object) and not d.users_collection]
        measured["scene users s"] = time.perf_counter() - start
        start = time.perf_counter()
        for scene in bpy.data.scenes:
            for view_layer in scene.view_layers:
                view_layer.update()
        measured["resync s"] = time.perf_counter() - start
        measured.update(
            {
                "obsolete": len(datablocks),
                "scene-used before resync": len(stale),
                "scene-used objects in no collection": len(unlinked),
                "scene-used after resync": len(_scene_used(bpy, datablocks)),
            }
        )
        start = time.perf_counter()
        try:
            return retire(binding_id, obsolete, operation)
        finally:
            measured["retire s"] = time.perf_counter() - start

    setattr(retirement, "retire", measuring)  # noqa: B010 - the transaction calls it through the module
    stage = Usd.Stage.Open(config["scene"])
    scene: Any = bpy.context.scene  # never None in a running Blender
    handle = api.BINDINGS.create_binding(scene, name="Profile")
    assert handle.attach(stage).is_success
    assert handle.synchronize(config["time"]).state is not ResultState.FATAL_FAILURE
    generation = sum(len(c) for c in (bpy.data.objects, bpy.data.meshes, bpy.data.actions))
    measured["armed"] = True
    start = time.perf_counter()
    result = handle.synchronize(config["time"])
    measured["synchronize again s"] = time.perf_counter() - start
    measured |= {
        "state": str(result.state),
        "generation datablocks": generation,
        "file datablocks after": sum(len(c) for c in (bpy.data.objects, bpy.data.meshes, bpy.data.actions)),
        "blender version": bpy.app.version_string,
    }
    del measured["armed"]
    Path(config["result"]).write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    from blender_paths import find_blender

    spec = importlib.util.spec_from_file_location("measure_run", HERE / "run_benchmarks.py")
    assert spec is not None and spec.loader is not None
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)
    profile_spec = importlib.util.spec_from_file_location("profile", HERE / "synchronization_profile.py")
    assert profile_spec is not None and profile_spec.loader is not None
    profile = importlib.util.module_from_spec(profile_spec)
    profile_spec.loader.exec_module(profile)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenes", nargs="+", default=["updates", "alab"], help="run_benchmarks.py's scene groups")
    parser.add_argument("--exclude", nargs="*", default=[], help="scenes of those groups to leave out")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=3600.0, help="per run (s)")
    parser.add_argument("--out", type=Path, default=ROOT / "build/hydra-bridge/retirement-after-undo-push")
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
    script = Path(__file__).resolve()
    results: dict[str, list[dict[str, Any]]] = {}
    for repeat in range(args.repeats):
        for name, scene in found.items():
            label = f"{name}-{repeat}"
            work = out / "work" / label
            config = {"scene": scene["path"], "time": scene["time"], "result": str(work / "result.json")}
            outcome = _run(args.blender, script, config, work, args.timeout, profile)
            (out / "runs" / f"{label}.json").write_text(json.dumps(outcome) + "\n")
            print(f"{label}: {'ok' if outcome['result'] else 'failed'}", flush=True)
            if outcome["result"]:
                results.setdefault(name, []).append(outcome["result"])
    summary = {
        name: {
            "runs": len(runs),
            **{k: v for k, v in runs[0].items() if not k.endswith(" s")},
            **{
                k: {"median": statistics.median(r[k] for r in runs), "min": min(r[k] for r in runs)}
                for k in runs[0]
                if k.endswith(" s")
            },
        }
        for name, runs in results.items()
    }
    setup = {"environment": run.environment(args.blender)}
    (out / "summary.json").write_text(json.dumps({"setup": setup, "summary": summary}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


def _run(blender: str, script: Path, config: dict[str, Any], work: Path, timeout: float, profile: Any) -> Any:
    """One child in the binary, through the profile's runner, with this script as the child."""
    original = profile.__file__
    profile.__file__ = str(script)  # run_once runs its own file as the child
    try:
        return profile.run_once(blender, config, work, timeout)
    finally:
        profile.__file__ = original


if __name__ == "__main__":
    if "--" in sys.argv and sys.argv[sys.argv.index("--") + 1] == "child":
        child(json.loads(Path(sys.argv[sys.argv.index("--") + 2]).read_text()))
    else:
        sys.exit(main())
