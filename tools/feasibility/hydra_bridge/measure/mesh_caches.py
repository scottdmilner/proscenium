"""M4 Phase E (E4): caching ALab's deforming meshes frame by frame, as per-frame attributes or as edited bakes.

    uv run python tools/feasibility/hydra_bridge/measure/mesh_caches.py VARIANT [--last FRAME] \
        [--out build/hydra-bridge/mesh-caches]

Runs in the bpy wheel, in one process. Synchronizes ALab, with its point instancers, at 1004 as the object
baseline, then streams each later frame through the bridge (an incremental capture, planning that reuses the
previous plan's builds, and the diff) and appends each varying mesh's positions for that frame to a cache in
Blender, as a cached display's synchronization would. VARIANT is:
- attributes: a point attribute P_<frame> per frame on the shared mesh, which a Geometry Nodes modifier on each
  copy reads by the current frame's name to set positions;
- bake-repack: a holder object per varying mesh, whose packed Geometry Nodes bake is unpacked to disk, given the
  frame's files (its meta JSON and a positions blob, sharing everything else with earlier frames), and packed
  again; each copy shows its holder's geometry through Object Info;
- bake-disk: the same holders, their bakes left on disk while they fill, reread by reassigning the modifier's
  node group (which resets the bake's settings, restored after), and packed once at the end.

Each frame times the stream, the append, the frame's evaluation, and an undo push with global undo on, with the
process footprint around the push. Then every frame is played back, a sample of meshes is checked against the
streamed positions, and the file is saved uncompressed. Writes <out>/<variant>.json. Each run starts by saving
an empty .blend, since bakes are written beside a saved file; nothing is written outside <out>.
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

import alab_entry  # noqa: E402
import apply  # noqa: E402
import bpy  # noqa: E402
import numpy  # noqa: E402
from memory import footprint, heap_in_use  # noqa: E402
from pxr import Usd  # noqa: E402

FIRST, LAST = 1004, 1057  # ALab's time codes, each a frame
SAMPLES = 3  # varying meshes checked against the streamed positions
CHECKED = (1005, 1030, 1057)
BUDGET_S = 2400  # filling stops once this much time has gone
CACHE_PREFIX = "P_"


def megabytes(value: int | None) -> float | None:
    return None if value is None else round(value / 2**20, 1)


def positions_of(record: dict[str, Any]) -> numpy.ndarray:
    return numpy.frombuffer(apply.flat(record["positions"], apply.BufferFormat.FLOAT), numpy.float32).copy()


def evaluated_positions(obj: bpy.types.Object) -> numpy.ndarray:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    geometry = obj.evaluated_get(depsgraph).evaluated_geometry()  # holds the evaluated mesh while it is read
    mesh: Any = geometry.mesh
    positions = numpy.empty(len(mesh.vertices) * 3, numpy.float32)
    mesh.vertices.foreach_get("co", positions)
    return positions


def frames_tree() -> bpy.types.NodeTree:
    """Set positions from the point attribute named for the current frame, where the mesh has one."""
    tree: Any = bpy.data.node_groups.new("Frames", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = tree.nodes, tree.links
    group_in, group_out = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    scene_time = nodes.new("GeometryNodeInputSceneTime")
    to_int = nodes.new("FunctionNodeFloatToInt")
    to_int.rounding_mode = "ROUND"
    text = nodes.new("FunctionNodeValueToString")
    prefix = nodes.new("FunctionNodeInputString")
    prefix.string = CACHE_PREFIX
    join = nodes.new("GeometryNodeStringJoin")
    named = nodes.new("GeometryNodeInputNamedAttribute")
    named.data_type = "FLOAT_VECTOR"
    set_position = nodes.new("GeometryNodeSetPosition")
    links.new(scene_time.outputs["Frame"], to_int.inputs[0])
    links.new(to_int.outputs[0], text.inputs["Value"])
    # Join Strings puts its newest link first, so the frame is linked before the prefix.
    links.new(text.outputs[0], join.inputs["Strings"])
    links.new(prefix.outputs[0], join.inputs["Strings"])
    links.new(join.outputs[0], named.inputs["Name"])
    links.new(group_in.outputs[0], set_position.inputs["Geometry"])
    links.new(named.outputs["Attribute"], set_position.inputs["Position"])
    links.new(named.outputs["Exists"], set_position.inputs["Selection"])  # an uncached frame keeps the mesh's own
    links.new(set_position.outputs[0], group_out.inputs[0])
    return tree


class Attributes:
    """Per-frame position attributes on the shared meshes: the attributes variant's cache."""

    tree: bpy.types.NodeTree
    meshes: dict[int, bpy.types.Mesh]  # by base mesh: the display's mesh, which holds the cache
    last: dict[int, numpy.ndarray]  # by base mesh: its latest positions, for a frame it holds still
    ops: dict[str, list[float]]

    def __init__(self) -> None:
        self.tree = frames_tree()
        self.meshes, self.last, self.ops = {}, {}, {}

    def start(self, base: int, mesh: bpy.types.Mesh, copies: list[bpy.types.Object]) -> None:
        for copy in copies:
            modifier: Any = copy.modifiers.new("Frames", "NODES")
            modifier.node_group = self.tree
        self.meshes[base] = mesh
        positions = numpy.empty(len(mesh.vertices) * 3, numpy.float32)
        mesh.vertices.foreach_get("co", positions)
        self.last[base] = positions
        self._write(mesh, FIRST, positions)

    @staticmethod
    def _write(mesh: bpy.types.Mesh, frame: int, positions: numpy.ndarray) -> None:
        attribute: Any = mesh.attributes.new(f"{CACHE_PREFIX}{frame}", "FLOAT_VECTOR", "POINT")
        attribute.data.foreach_set("vector", positions)

    def append(self, frame: int, positions: dict[int, numpy.ndarray | None]) -> None:
        """Frame `frame` for each base mesh: its new positions, or None for those of its previous frame."""
        for base, points in positions.items():
            if points is not None:
                self.last[base] = points
            self._write(self.meshes[base], frame, self.last[base])

    def finish(self) -> float:
        return 0.0


class Bakes:
    """A holder object per varying mesh, with a Geometry Nodes bake: the bake variants' cache."""

    work: Path
    packed: bool  # bake-repack keeps each bake packed between frames
    baked: bpy.types.NodeTree  # a holder's: its own geometry through a Bake node
    shown: bpy.types.NodeTree  # a copy's: its holder's geometry, untransformed
    socket: str  # the identifier of the copy tree's holder input
    collection: bpy.types.Collection
    holders: dict[int, bpy.types.Object]  # by base mesh
    last_frame: dict[int, int]  # by base mesh: the latest frame its bake holds
    # By holder name: its bake's directory. Blender names it after the object, its name escaped, so it is found as
    # the one the first bake creates; every holder's bake has the shared node's identifier.
    directories: dict[str, Path]
    ops: dict[str, list[float]]  # seconds of each operator call, and of each reload, by kind

    def __init__(self, work: Path, packed: bool) -> None:
        self.work, self.packed = work, packed
        self.baked, self.shown, self.socket = self._trees()
        self.collection = bpy.data.collections.new("Holders")
        scene: Any = bpy.context.scene
        scene.collection.children.link(self.collection)
        self.holders, self.last_frame, self.directories = {}, {}, {}
        self.ops = {"bake": [], "unpack": [], "pack": [], "reload": []}

    @staticmethod
    def _trees() -> tuple[bpy.types.NodeTree, bpy.types.NodeTree, str]:
        baked: Any = bpy.data.node_groups.new("Baked", "GeometryNodeTree")
        baked.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        baked.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        group_in, group_out = baked.nodes.new("NodeGroupInput"), baked.nodes.new("NodeGroupOutput")
        bake = baked.nodes.new("GeometryNodeBake")
        bake.bake_items.new("GEOMETRY", "Geometry")
        baked.links.new(group_in.outputs[0], bake.inputs[0])
        baked.links.new(bake.outputs[0], group_out.inputs[0])
        shown: Any = bpy.data.node_groups.new("FromHolder", "GeometryNodeTree")
        shown.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        socket = shown.interface.new_socket("Holder", in_out="INPUT", socket_type="NodeSocketObject")
        shown.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        group_in, group_out = shown.nodes.new("NodeGroupInput"), shown.nodes.new("NodeGroupOutput")
        info = shown.nodes.new("GeometryNodeObjectInfo")
        info.transform_space = "ORIGINAL"
        shown.links.new(group_in.outputs["Holder"], info.inputs["Object"])
        shown.links.new(info.outputs["Geometry"], group_out.inputs[0])
        return baked, shown, socket.identifier

    def _op(self, kind: str, holder: bpy.types.Object, **extra: Any) -> None:
        modifier: Any = holder.modifiers["Bake"]
        kwargs = {
            "session_uid": holder.session_uid,
            "modifier_name": modifier.name,
            "bake_id": modifier.bakes[0].bake_id,
        }
        call: Any = {
            "bake": bpy.ops.object.geometry_node_bake_single,
            "unpack": bpy.ops.object.geometry_node_bake_unpack_single,
            "pack": bpy.ops.object.geometry_node_bake_pack_single,
        }[kind]
        start = time.perf_counter()
        holder.hide_viewport = False  # the bake operators refuse a hidden object
        override = bpy.context.temp_override(object=holder, active_object=holder, selected_objects=[holder])
        with override:  # ty: ignore[invalid-context-manager] - the stubs don't declare it a context manager
            result = call(**kwargs, **extra)
        holder.hide_viewport = True
        self.ops[kind].append(time.perf_counter() - start)
        if result != {"FINISHED"}:
            raise RuntimeError(f"{kind} of {holder.name}: {result}")

    @staticmethod
    def _settings(bake: Any, end: int) -> None:
        bake.bake_mode = "ANIMATION"
        bake.use_custom_simulation_frame_range = True
        bake.frame_start, bake.frame_end = FIRST, end
        bake.bake_target = "DISK"

    def start(self, base: int, mesh: bpy.types.Mesh, copies: list[bpy.types.Object]) -> None:
        """A holder of `mesh`, baked at the first frame, and each copy showing it."""
        holder = bpy.data.objects.new(f"holder {base:05d}", mesh)
        self.collection.objects.link(holder)
        holder.hide_viewport = holder.hide_render = True
        modifier: Any = holder.modifiers.new("Bake", "NODES")
        modifier.node_group = self.baked
        self._settings(modifier.bakes[0], FIRST)
        before = set(self.work.glob("blendcache_*/*/*"))
        self._op("bake", holder)
        (self.directories[holder.name],) = set(self.work.glob("blendcache_*/*/*")) - before
        if self.packed:
            self._op("pack", holder)
        for copy in copies:
            shown: Any = copy.modifiers.new("FromHolder", "NODES")
            shown.node_group = self.shown
            getattr(shown.properties.inputs, self.socket).value = holder  # Blender 5.2's modifier inputs
        self.holders[base] = holder
        self.last_frame[base] = FIRST

    def append(self, frame: int, positions: dict[int, numpy.ndarray | None]) -> None:
        """Frame `frame` for each holder: its new positions, or None for those of its previous frame."""
        for base, points in positions.items():
            holder = self.holders[base]
            if self.packed:
                self._op("unpack", holder, method="WRITE_LOCAL")
            directory = self.directories[holder.name]
            meta = json.loads((directory / "meta" / f"{self.last_frame[base]:05d}_00000.json").read_text())
            if points is not None:  # a positions blob; every other array stays shared with the earlier frame's
                name = f"{frame:05d}_00000.blob"
                (directory / "blobs" / name).write_bytes(points.astype("<f4").tobytes())
                for attribute in meta["items"]["0"]["data"]["mesh"]["attributes"]:
                    if attribute["name"] == "position":
                        attribute["data"] = {"name": name, "start": 0, "size": points.nbytes}
            (directory / "meta" / f"{frame:05d}_00000.json").write_text(json.dumps(meta))
            self.last_frame[base] = frame
            modifier: Any = holder.modifiers["Bake"]
            if self.packed:
                modifier.bakes[0].frame_end = frame
                self._op("pack", holder)
            else:
                start = time.perf_counter()
                modifier.node_group = None  # rereads the bake from disk, and resets its settings
                modifier.node_group = self.baked
                self._settings(modifier.bakes[0], frame)
                self.ops["reload"].append(time.perf_counter() - start)

    def finish(self) -> float:
        """Pack the bakes left on disk; returns the seconds it took."""
        start = time.perf_counter()
        if not self.packed:
            for holder in self.holders.values():
                self._op("pack", holder)
        return time.perf_counter() - start


def series(steps: list[dict[str, Any]], key: str) -> dict[str, float]:
    """A per-frame measurement's median, its medians over the first and last tenth of the frames, and its total."""
    values = [step[key] for step in steps if step[key] is not None]
    tenth = max(1, len(values) // 10)
    return {
        "median": round(statistics.median(values), 4),
        "first tenth": round(statistics.median(values[:tenth]), 4),
        "last tenth": round(statistics.median(values[-tenth:]), 4),
        "total": round(sum(values), 2),
    }


def main() -> int:  # noqa: PLR0915 - one run, start to end
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("variant", choices=["attributes", "bake-repack", "bake-disk"])
    parser.add_argument("--last", type=int, default=LAST, help="the last frame to stream")
    parser.add_argument("--out", type=Path, default=ROOT / "build/hydra-bridge/mesh-caches")
    parser.add_argument("--module-dir", type=Path, default=ROOT / "build/hydra-bridge")
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    alab = os.environ.get("PROSCENIUM_ALAB_ROOT")
    if not alab:
        raise SystemExit("needs PROSCENIUM_ALAB_ROOT (environment or .env)")
    out: Path = args.out.resolve()
    work = out / f"work-{args.variant}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    entry = out / "alab_instancers_entry.usda"
    entry.unlink(missing_ok=True)
    alab_entry.write(Path(alab) / "entry.usda", entry, point_instancers=True)
    sys.path.insert(0, str(args.module_dir))
    import _hydra_bridge as native  # ty: ignore[unresolved-import] - built into build/hydra-bridge

    bpy.ops.wm.read_factory_settings(use_empty=True)
    preferences: Any = bpy.context.preferences
    preferences.edit.use_global_undo = True
    scene: Any = bpy.context.scene
    scene.frame_start, scene.frame_end = FIRST, args.last
    scene.frame_set(FIRST)
    bpy.ops.wm.save_as_mainfile(filepath=str(work / "cache.blend"))  # bakes are written beside a saved file

    stage = Usd.Stage.Open(str(entry))
    bridge = native.Bridge(stage)
    start = time.perf_counter()
    plan = native.build_plan(bridge.capture(float(FIRST)))
    collection = bpy.data.collections.new("Prototype")
    scene.collection.children.link(collection)
    display = apply.apply(plan, collection)
    view_layer: Any = bpy.context.view_layer  # never None in a running Blender
    view_layer.update()
    synchronized = time.perf_counter() - start
    records = plan.objects
    base_of = {(r["source"], tuple(r["instance_context"])): r["mesh"] for r in records if r["mesh"] is not None}
    copies_of: dict[int, list[bpy.types.Object]] = {}
    for index, record in enumerate(records):
        if record["mesh"] is not None:
            copies_of.setdefault(record["mesh"], []).append(display.objects[index])
    cache = Attributes() if args.variant == "attributes" else Bakes(work, packed=args.variant == "bake-repack")
    bpy.ops.ed.undo_push(message="synchronized")
    process = os.getpid()
    memory = {"start footprint MB": megabytes(footprint(process)), "start heap MB": megabytes(heap_in_use())}

    varying: set[int] = set()
    streamed: dict[int, dict[int, numpy.ndarray]] = {}  # sampled base meshes: their new positions by frame
    steps: list[dict[str, Any]] = []
    topology_changed: set[int] = set()
    previous = plan
    began = time.perf_counter()
    for frame in range(FIRST + 1, args.last + 1):
        step: dict[str, Any] = {"frame": frame}
        clock = time.perf_counter()
        plan = native.build_plan(bridge.capture(float(frame), incremental=True), previous=previous)
        diff = native.diff_plans(previous, plan)
        new_by_base: dict[int, int] = {}  # by base mesh: its new mesh in this frame's plan
        for record in plan.objects_at(diff["changed_object_indices"]):
            mesh = record["mesh"]
            if mesh is not None and diff["previous_mesh_indices"][mesh] == -1:
                new_by_base[base_of[(record["source"], tuple(record["instance_context"]))]] = mesh
        order = sorted(set(new_by_base.values()))
        meshes = dict(zip(order, plan.meshes_at(order), strict=True))
        positions: dict[int, numpy.ndarray | None] = {}
        for base, mesh in new_by_base.items():
            points = positions_of(meshes[mesh])
            if len(points) == 3 * len(display.meshes[base].vertices):
                positions[base] = points
            else:
                topology_changed.add(base)  # beyond what a positions cache holds
        step["stream s"] = time.perf_counter() - clock
        clock = time.perf_counter()
        for base in sorted(set(positions) - varying):
            cache.start(base, display.meshes[base], copies_of[base])
            varying.add(base)
            if len(streamed) < SAMPLES:
                streamed[base] = {}
        positions |= dict.fromkeys(varying - set(positions))  # held: each keeps its previous frame's positions
        cache.append(frame, positions)
        step["append s"] = time.perf_counter() - clock
        for base, by_frame in streamed.items():
            points = positions.get(base)
            if points is not None:
                by_frame[frame] = points
        step["new positions"] = sum(points is not None for points in positions.values())
        clock = time.perf_counter()
        scene.frame_set(frame)
        step["evaluate s"] = time.perf_counter() - clock
        before = footprint(process)
        clock = time.perf_counter()
        bpy.ops.ed.undo_push(message=f"frame {frame}")
        step["undo push s"] = time.perf_counter() - clock
        after = footprint(process)
        step["undo push footprint MB"] = megabytes(None if before is None or after is None else after - before)
        steps.append(step)
        previous = plan
        print(json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in step.items()}), flush=True)
        if time.perf_counter() - began > BUDGET_S:
            print("budget reached", flush=True)
            break
    last = steps[-1]["frame"]
    finish = cache.finish()
    memory |= {"filled footprint MB": megabytes(footprint(process)), "filled heap MB": megabytes(heap_in_use())}

    playback = []
    for frame in range(FIRST, last + 1):
        clock = time.perf_counter()
        scene.frame_set(frame)
        playback.append(time.perf_counter() - clock)
    errors = {}
    for base, by_frame in streamed.items():
        for frame in CHECKED:
            held = [f for f in by_frame if f <= frame]
            if frame <= last and held:
                scene.frame_set(frame)
                difference = evaluated_positions(copies_of[base][0]) - by_frame[max(held)]
                errors[f"{base}@{frame}"] = float(numpy.abs(difference).max())

    blend = work / "final.blend"
    clock = time.perf_counter()
    bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=False)
    saved = time.perf_counter() - clock
    left = sum(p.stat().st_size for p in work.glob("blendcache_*/**/*") if p.is_file())
    bridge.release()

    result = {
        "variant": args.variant,
        "runtime": f"bpy wheel {bpy.app.version_string}, in-process",
        "frames streamed": len(steps),
        "last frame": last,
        "initial synchronization s": round(synchronized, 2),
        "varying meshes": len(varying),
        "their copies": sum(len(copies_of[base]) for base in varying),
        "topology changed (not cached)": len(topology_changed),
        "per frame": {key: series(steps, key) for key in ("stream s", "append s", "evaluate s", "undo push s")},
        "undo push footprint MB": series(steps, "undo push footprint MB"),
        "finish (pack) s": round(finish, 2),
        "operators": {
            kind: {"count": len(seconds), "median s": round(statistics.median(seconds), 4)}
            for kind, seconds in cache.ops.items()
            if seconds
        },
        "memory": memory,
        "playback (revisit) s": {"median": round(statistics.median(playback), 4), "max": round(max(playback), 4)},
        "max position error at checked frames": errors,
        "blend MB": megabytes(blend.stat().st_size),
        "save s": round(saved, 2),
        "bake files left on disk MB": megabytes(left),
        "frames": steps,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.variant}.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "frames"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
