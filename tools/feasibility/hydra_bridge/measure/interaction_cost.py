"""The product's interaction calls, the binding panel's listing, and the tool's ray loop, timed in the Blender binary.

    uv run python tools/feasibility/hydra_bridge/measure/interaction_cost.py [--scenes updates alab] \
        [--exclude updates-100] [--repeats 3]

M7 plan, Phase G (item 4), against M4's provisional budgets: 50 ms for a function on one pick or entry and 250 ms on
a whole-assembly selection, with their Blender updates ([M4 plan](../../../../docs/plans/M04-prototypes.md)). Each run
makes a binding through the API (proscenium.api.bindings), attaches the scene's stage, synchronizes at its time code,
caches CACHED later ones, makes the scene's managed content selectable, and updates the view layer. Then each
operation is timed in process with a monotonic clock, repeated (SINGLE_REPEATS, or WHOLE_REPEATS for those over the
whole display), and its median and range kept; the summary gives the median and range of the processes' medians.

The pick is the managed object whose copy has the deepest instance context, at the API's levels: the prim (None),
component, and assembly. An API call builds the binding's correspondence from its manifest and hide flags, or reuses
the one api/shown_displays.py keeps, reading the hide flags, so each time includes that. An operation that changes
Blender's selection is timed with the view layer update after it, as a window's redraw would evaluate the depsgraph.
The box selection takes every element (inside always true) after projecting its world bounds' center through a fixed
matrix, standing in for the region's projection. The tool's ray loop is `source_select_tool.bounds_ray_cast` over
`pickable`'s objects with a ray straight down through the pick's bounds center; its marker test says no. The
inspector's per-draw reads are `displayed` for one prim and `shown_time_code`. Raw runs go to <out>/runs/, the summary
to <out>/summary.json and summary.md.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(HERE), str(ROOT / "tools")]

if TYPE_CHECKING:
    from collections.abc import Callable

CACHED = 3
SINGLE_REPEATS = 20
WHOLE_REPEATS = 5
SCENES = ["updates", "alab"]  # run_benchmarks.py's groups
LEVELS: tuple[str | None, ...] = (None, "component", "assembly")


def _timed(repeats: int, call: Callable[[], Any]) -> dict[str, float]:
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        call()
        times.append(time.perf_counter() - start)
    return {"median": statistics.median(times), "min": min(times), "max": max(times), "repeats": repeats}


def child(config: dict[str, Any]) -> None:
    """One run, its result written where the config says."""
    import bpy
    from mathutils import Matrix, Vector

    sys.path.insert(0, str(ROOT / "src"))
    from pxr import Usd

    from proscenium.api import binding_interaction
    from proscenium.api import bindings as api
    from proscenium.interface import source_select_tool

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene: Any = bpy.context.scene
    at = config["time"]
    scene.frame_set(int(at))
    stage = Usd.Stage.Open(config["scene"])
    handle = api.BINDINGS.create_binding(scene, name="Interaction")
    assert handle.attach(stage).is_success
    assert handle.synchronize(at).is_success
    assert handle.cache([at + 1 + i for i in range(CACHED)]).is_success
    api.BINDINGS.set_managed_selectable(scene, True)

    def view_layer() -> Any:
        return bpy.context.view_layer

    view_layer().update()
    managed = list(bpy.data.collections["Interaction"].all_objects)

    # The pick: the object whose picked copy has the deepest instance context, from one correspondence, since each
    # API call builds its own.
    shown = binding_interaction.shown_display(api.BINDINGS, handle.binding_id)
    elements = shown.elements
    assert elements is not None

    def depth(element_index: int) -> int:
        obj = elements.objects[element_index]
        world_matrix = binding_interaction.usd_matrix(obj.matrix_world)
        picked = shown.correspondence.resolve_pick(element_index, world_matrix) if obj.type == "MESH" else None
        return -1 if picked is None else len(picked.instance_context)

    picked_object = elements.objects[max(range(len(elements.objects)), key=depth)]
    matrix = picked_object.matrix_world.copy()
    picked = handle.resolve_pick(picked_object, matrix)
    assert picked is not None
    entity = picked.source_path
    results: dict[str, Any] = {}

    def with_update(call: Callable[[], Any]) -> Callable[[], None]:
        def run() -> None:
            call()
            view_layer().update()

        return run

    # The headless functions on the pick.
    results["resolve_pick"] = _timed(SINGLE_REPEATS, lambda: handle.resolve_pick(picked_object, matrix))
    targets = {}
    for level in LEVELS:
        name = level or "prim"
        results[f"select_targets, {name}"] = _timed(
            SINGLE_REPEATS, lambda lv=level: handle.select_targets([entity], lv)
        )
        targets[name] = handle.select_targets([entity], level)
    results["highlight_targets, component"] = _timed(
        SINGLE_REPEATS, lambda: handle.highlight_targets(targets["component"])
    )
    for level in LEVELS:
        results[f"selection_from_blender, {level or 'prim'}"] = _timed(
            SINGLE_REPEATS, lambda lv=level: handle.selection_from_blender(lv, view_layer())
        )

    # The scene's source selection, each with its mirroring and the update after it.
    entry = api.SelectionEntry(handle.binding_id, targets["component"][0])
    one = api.PersistentSelection((entry,), entry)
    empty = api.PersistentSelection((), None)
    results["set_source_selection, one entry"] = _timed(
        SINGLE_REPEATS,
        with_update(
            lambda: (api.BINDINGS.set_source_selection(scene, empty), api.BINDINGS.set_source_selection(scene, one))
        ),
    )
    results["select_by_pick, component"] = _timed(
        SINGLE_REPEATS, with_update(lambda: api.BINDINGS.select_by_pick(scene, picked_object, matrix, "component"))
    )
    results["resolve_source_selection, one entry"] = _timed(
        SINGLE_REPEATS, lambda: api.BINDINGS.resolve_source_selection(scene)
    )
    results["mirror_after_frame_change, one entry"] = _timed(
        SINGLE_REPEATS, with_update(lambda: api.BINDINGS.mirror_after_frame_change(scene))
    )
    projection = Matrix.Translation((0.5, 0.5, 0.0)) @ Matrix.Scale(0.001, 4)  # stands in for the region's projection

    def project(point: Vector) -> Vector:
        return (projection @ point.to_4d()).xy

    def inside(point: Vector) -> bool:
        return project(point) is not None  # every element

    for level in ("component", "assembly"):
        results[f"select_by_box, every element, {level}"] = _timed(
            WHOLE_REPEATS, with_update(lambda lv=level: api.BINDINGS.select_by_box(scene, inside, lv))
        )
    whole = api.BINDINGS.source_selection(scene)
    results["resolve_source_selection, whole box"] = _timed(
        WHOLE_REPEATS, lambda: api.BINDINGS.resolve_source_selection(scene)
    )
    results["mirror_after_frame_change, whole box"] = _timed(
        WHOLE_REPEATS, with_update(lambda: api.BINDINGS.mirror_after_frame_change(scene))
    )
    results["switch selectability off and on"] = _timed(
        WHOLE_REPEATS,
        with_update(
            lambda: (
                api.BINDINGS.set_managed_selectable(scene, False),
                api.BINDINGS.set_managed_selectable(scene, True),
            )
        ),
    )

    # The temporary UI's per-draw reads and the tool's ray loop.
    results["binding_statuses"] = _timed(SINGLE_REPEATS, lambda: api.BINDINGS.binding_statuses(scene))
    results["displayed, one prim"] = _timed(SINGLE_REPEATS, lambda: handle.displayed([entity]))
    results["shown_time_code"] = _timed(SINGLE_REPEATS, handle.shown_time_code)
    results["pickable"] = _timed(SINGLE_REPEATS, lambda: source_select_tool.pickable(view_layer()))
    center = picked_object.matrix_world @ (sum((Vector(corner) for corner in picked_object.bound_box), Vector()) / 8)
    origin, down = center + Vector((0.0, 0.0, 1.0e4)), Vector((0.0, 0.0, -1.0))
    results["bounds_ray_cast"] = _timed(
        SINGLE_REPEATS,
        lambda: source_select_tool.bounds_ray_cast(
            source_select_tool.pickable(view_layer()), origin, down, lambda _obj: False
        ),
    )
    result = {
        "timings": results,
        "objects": len(managed),
        "pickable": len(source_select_tool.pickable(view_layer())),
        "pick": {"object": picked_object.name, "entity": entity, "instance depth": len(picked.instance_context)},
        "targets": {name: list(paths) for name, paths in targets.items()},
        "whole box entries": len(whole.entries),
        "blender version": bpy.app.version_string,
    }
    Path(config["result"]).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """By scene and operation: the median and range of the processes' medians."""
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
            entry |= {key: first[key] for key in ("objects", "pickable", "pick", "targets", "whole box entries")}
            entry["timings"] = {
                operation: {
                    "repeats": timing["repeats"],
                    "median": statistics.median(r["timings"][operation]["median"] for r in results),
                    "min": min(r["timings"][operation]["median"] for r in results),
                    "max": max(r["timings"][operation]["median"] for r in results),
                }
                for operation, timing in first["timings"].items()
            }
        summary[name] = entry
    return summary


def markdown(summary: dict[str, Any], setup: dict[str, Any]) -> str:
    names = [name for name, entry in summary.items() if entry["runs"]]
    lines = ["# The product's interaction (M7 Phase G)", "", f"Setup: {json.dumps(setup)}", ""]
    for name, entry in summary.items():
        if not entry["runs"]:
            lines += [f"{name} failed: {entry['failed'][:1]}", ""]
            continue
        lines.append(
            f"- {name}: {entry['objects']:,} objects, {entry['pickable']:,} pickable; pick {entry['pick']}; "
            f"whole box {entry['whole box entries']:,} entries"
        )
    lines += ["", "| Operation (ms) | Repeats | " + " | ".join(names) + " |", "|---|---|" + "---|" * len(names)]
    operations = summary[names[0]]["timings"] if names else {}
    for operation, timing in operations.items():
        cells = []
        for name in names:
            stat = summary[name]["timings"][operation]
            cells.append(f"{stat['median'] * 1000:,.3f} ({stat['min'] * 1000:,.3f}-{stat['max'] * 1000:,.3f})")
        lines.append(f"| {operation} | {timing['repeats']} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    import synchronization_profile

    from blender_paths import find_blender

    spec = importlib.util.spec_from_file_location("measure_run", HERE / "run_benchmarks.py")
    assert spec is not None and spec.loader is not None
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenes", nargs="+", default=SCENES, help="run_benchmarks.py's scene groups")
    parser.add_argument("--exclude", nargs="*", default=[], help="scenes of those groups to leave out")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=3600.0, help="per run (s)")
    parser.add_argument("--out", type=Path, default=ROOT / "build/hydra-bridge/interaction-cost")
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
                "work": str(work),
                "result": str(work / "result.json"),
            }
            # The profile's runner starts this script's child in the binary.
            config["script"] = str(Path(__file__).resolve())
            result = synchronization_profile.run_once(args.blender, config, work, args.timeout)
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
