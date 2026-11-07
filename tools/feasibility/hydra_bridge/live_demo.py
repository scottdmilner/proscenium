"""Display a USD file through the Hydra bridge, and update it from disk at the click of a button (demo).

    blender --python tools/feasibility/hydra_bridge/live_demo.py -- SCENE.usd [--time T] [--follow] [--select]

Or open this file in Blender's Text Editor, set SCENE below (or the PROSCENIUM_DEMO_SCENE environment variable),
and press Run Script. Running it again replaces the previous session.

Another program, such as Houdini's Solaris writing the scene with a USD ROP, saves the file. The Update from USD
button in the 3D view's sidebar (N, Proscenium tab) reloads each of the stage's layers whose file changed and
synchronizes through the update path (snapshots.py): an incremental capture, a plan reusing the previous one's mesh
builds, the plan diff, and an update by it that rebuilds only what changed. The sidebar and a viewport overlay show
each update. With --select, the display is batched (batch.py) and Source Select (select_tool.py) becomes the
active tool, its interaction rebuilt over each update's plan, keeping the targets the new plan still has.
With --follow, the display also synchronizes at each frame's time code. Without --select, a Y-up stage is shown Z-up
through a rotated collection instance; Blender selects only objects in the view layer, so with --select it is shown
as authored. Expects the bridge built by build.py in build/hydra-bridge/. Nothing is saved.
"""

from __future__ import annotations

import argparse
import os
import sys
import time as clock
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import bpy

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

SCENE = ""  # the scene to display when run from the Text Editor without PROSCENIUM_DEMO_SCENE


def _here() -> Path:
    """This file's directory, also when Blender runs it as a Text Editor text."""
    candidates = [Path(globals().get("__file__", ""))]
    candidates += [Path(bpy.path.abspath(text.filepath)) for text in bpy.data.texts if text.filepath]
    for candidate in candidates:
        if candidate.name == "live_demo.py" and (candidate.resolve().parent / "snapshots.py").exists():
            return candidate.resolve().parent
    raise RuntimeError("Can't find tools/feasibility/hydra_bridge: open live_demo.py from disk, not a copy")


HERE = _here()
sys.path[:0] = [p for p in (str(HERE), str(HERE.parents[2] / "build/hydra-bridge")) if p not in sys.path]

import _hydra_bridge as native  # noqa: E402  # ty: ignore[unresolved-import] - built into build/hydra-bridge
import batch  # noqa: E402
import blf  # noqa: E402
import select_outline  # noqa: E402
import select_tool  # noqa: E402
import snapshots  # noqa: E402
from pxr import Sdf, Usd, UsdGeom  # noqa: E402

SESSION_KEY = "proscenium_live_demo"  # where the running session is kept, in bpy.app.driver_namespace


@dataclass
class Session:
    """A live display of one USD file: its stage, the bridge's synchronized display, and what the overlay shows."""

    path: Path
    stage: Usd.Stage
    display: snapshots.Snapshots
    collection: bpy.types.Collection
    instancer: bpy.types.Object | None  # the rotated collection instance of a Y-up stage
    time: float
    follow: bool
    select: bool  # whether Source Select runs over the (batched) display
    mtimes: dict[str, float] = field(default_factory=dict)  # by layer file: its time at the last synchronization
    updates: int = 0
    status: list[str] = field(default_factory=list)  # the overlay's lines below the title
    error: str | None = None
    draw_handle: Any = None

    def refresh(self) -> None:
        """Reload each layer whose file changed since the last synchronization, and synchronize."""
        try:
            start = clock.perf_counter()
            changed = [p for p, t in _mtimes(self.stage).items() if t != self.mtimes.get(p)]
            for path in changed:
                layer = Sdf.Layer.Find(path)
                if layer is not None:
                    layer.Reload(force=True)
            reason = f"{', '.join(Path(p).name for p in changed)} changed" if changed else "no file changed"
            self.synchronize(self.time, start, reason)
        except Exception:  # noqa: BLE001 - shown in the sidebar, overlay, and console; the next click retries
            self.fail()

    def synchronize(self, time: float, start: float, reason: str) -> None:
        """Update the display by the stage at `time`, and say what changed."""
        step = self.display.step(time)
        total = clock.perf_counter() - start
        self.mtimes = _mtimes(self.stage)
        if self.select:
            _select_over(self)
        self.updates += 1
        self.error = None
        diff = step.diff
        added = sum(1 for old in diff["objects"] if old == -1)
        rebuilt_meshes = sum(1 for old in diff["meshes"] if old == -1)
        plan = step.plan
        self.status = [
            f"Update {self.updates}: {reason}",
            f"+{added} added   ~{len(diff['changed'])} changed   -{len(diff['removed'])} removed   "
            f"{rebuilt_meshes} meshes rebuilt",
            f"{plan.object_count} objects, {plan.mesh_count} meshes, {plan.material_count} materials at time {time:g}",
            f"{total * 1000:.0f} ms: "
            + ", ".join(f"{name} {seconds * 1000:.0f}" for name, seconds in step.seconds.items()),
        ]
        print("[proscenium] " + " | ".join(self.status))
        _redraw()

    def fail(self) -> None:
        self.error = traceback.format_exc().strip().splitlines()[-1]
        traceback.print_exc()
        _redraw()

    def on_frame(self, scene: bpy.types.Scene, _depsgraph: Any = None) -> None:
        if scene == bpy.context.scene:
            self.time = scene.frame_current + scene.frame_subframe
            try:
                self.synchronize(self.time, clock.perf_counter(), f"frame {self.time:g}")
            except Exception:  # noqa: BLE001 - shown in the overlay and console
                self.fail()

    def draw_overlay(self) -> None:
        """The overlay: the source, then the latest update or error."""
        font = 0
        blf.size(font, 15)
        lines = [(f"Proscenium Hydra bridge: live from {self.path.name}", (1.0, 1.0, 1.0, 1.0))]
        lines += [(line, (0.8, 0.9, 1.0, 1.0)) for line in self.status]
        if self.error:
            lines.append((f"Error: {self.error}", (1.0, 0.4, 0.4, 1.0)))
        y = 60 + 22 * len(lines)
        for text, color in lines:
            blf.color(font, *color)
            blf.position(font, 20, y, 0)
            blf.draw(font, text)
            y -= 22

    def stop(self) -> None:
        """Unregister the session and remove its display."""
        if self.on_frame in bpy.app.handlers.frame_change_pre:
            bpy.app.handlers.frame_change_pre.remove(self.on_frame)
        if self.draw_handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self.draw_handle, "WINDOW")
        if self.select and select_tool.SESSION is not None:
            select_tool.unregister()
        display = self.display.display
        objects = list(self.collection.all_objects)
        # With batches, the carriers' points meshes and their node group too.
        data = {obj.data for obj in objects if obj.data is not None}
        nodes = [display.nodes.tree] if isinstance(display, batch.BatchedDisplay) else []
        bpy.data.batch_remove({*objects, *data, *display.meshes, *display.materials, *nodes})
        if self.instancer is not None:
            bpy.data.objects.remove(self.instancer)
        bpy.data.collections.remove(self.collection)
        self.display.release()
        _redraw()


class PROSCENIUM_OT_live_update(bpy.types.Operator):  # noqa: N801 - Blender's operator naming
    """Reload the changed USD layers and update the display."""

    bl_idname = "proscenium.live_update"
    bl_label = "Update from USD"

    @classmethod
    @override
    def poll(cls, context: Any) -> bool:
        return SESSION_KEY in bpy.app.driver_namespace

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        session: Session = bpy.app.driver_namespace[SESSION_KEY]
        session.refresh()
        if session.error:
            self.report({"ERROR"}, session.error)
            return {"CANCELLED"}
        return {"FINISHED"}


class PROSCENIUM_PT_live(bpy.types.Panel):  # noqa: N801 - Blender's panel naming
    """The sidebar's Proscenium tab: the source, the update button, and the latest update."""

    bl_label = "Proscenium Live"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Proscenium"

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout
        session: Session | None = bpy.app.driver_namespace.get(SESSION_KEY)
        if session is None:
            layout.label(text="No USD session: run live_demo.py")
            return
        layout.label(text=session.path.name, icon="FILE")
        row = layout.row()
        row.scale_y = 1.6
        row.operator(PROSCENIUM_OT_live_update.bl_idname, icon="FILE_REFRESH")
        column = layout.column(align=True)
        for line in session.status:
            column.label(text=line)
        if session.error:
            layout.label(text=session.error, icon="ERROR")


CLASSES = (PROSCENIUM_OT_live_update, PROSCENIUM_PT_live)


def _register_classes() -> None:
    """Register the operator and panel, replacing those of an earlier run."""
    for cls in CLASSES:
        earlier = getattr(bpy.types, cls.__name__, None)
        if earlier is not None:
            bpy.utils.unregister_class(earlier)
        bpy.utils.register_class(cls)


def _select_over(session: Session) -> None:
    """Install Source Select over the session's display, or move it onto the display's latest plan."""
    display = session.display
    interaction = native.Interaction(session.stage, display.plan)
    view_layer: Any = bpy.context.view_layer  # never None in a running Blender
    selection = select_tool.Session(
        interaction,
        display.display,
        view_layer,
        session.collection,
        keep=(session.stage, display.bridge, display.plan),
        stage=session.stage,
        time=session.time,
    )
    earlier = select_tool.SESSION
    if earlier is None:
        select_tool.register(selection)
        return
    selection.level, selection.following, selection.selectable = earlier.level, earlier.following, earlier.selectable
    # The targets whose prims the new plan still draws; Phase 2 keeps a selection whose identities stay valid.
    selection.targets = [t for t in earlier.targets if interaction.highlight_targets([t])]
    selection.active = earlier.active if earlier.active in selection.targets else None
    drawing = select_tool.OUTLINES is not None and select_tool.OUTLINES.draw_outlines
    if select_tool.OUTLINES is not None:
        select_tool.OUTLINES.disable()
    select_tool.SESSION = selection
    select_tool.OUTLINES = select_outline.Outlines(selection, draw_outlines=drawing)
    select_tool.OUTLINES.enable()
    selection.apply()


def start(path: Path, time: float | None, follow: bool, select: bool) -> Session:  # noqa: PLR0915 - one setup
    """Display `path` at `time` (the stage's start by default)."""
    previous = bpy.app.driver_namespace.pop(SESSION_KEY, None)
    if previous is not None:
        previous.stop()
    stage = Usd.Stage.Open(str(path))
    if not stage:
        raise RuntimeError(f"Can't open {path}")
    scene: Any = bpy.context.scene
    if follow:
        time = scene.frame_current
    elif time is None:
        time = stage.GetStartTimeCode()
    collection = bpy.data.collections.new(f"USD {path.stem}")
    instancer = None
    if UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y and not select:
        instancer = bpy.data.objects.new(f"USD {path.stem} (Y up)", None)
        instancer.instance_type = "COLLECTION"
        instancer.instance_collection = collection
        instancer.rotation_euler = (1.5707963267948966, 0.0, 0.0)
        scene.collection.objects.link(instancer)
    else:
        scene.collection.children.link(collection)
    begun = clock.perf_counter()
    representation = "batched" if select else "objects"
    display = snapshots.Snapshots(native, stage, collection, time, representation=representation, moves=True)
    session = Session(path, stage, display, collection, instancer, time, follow, select)
    session.mtimes = _mtimes(stage)
    plan = display.plan
    session.status = [
        f"Synchronized in {(clock.perf_counter() - begun) * 1000:.0f} ms: {plan.object_count} objects, "
        f"{plan.mesh_count} meshes, {plan.material_count} materials at time {time:g}",
        "Save the USD file, then click Update from USD.",
    ]
    print("[proscenium] " + " | ".join(session.status))
    bpy.app.driver_namespace[SESSION_KEY] = session
    _register_classes()
    if select:
        _select_over(session)
    if follow:
        bpy.app.handlers.frame_change_pre.append(session.on_frame)
    if not bpy.app.background:
        session.draw_handle = bpy.types.SpaceView3D.draw_handler_add(session.draw_overlay, (), "WINDOW", "POST_PIXEL")
        bpy.app.timers.register(lambda: _frame_all(select), first_interval=0.3)
    return session


def _mtimes(stage: Usd.Stage) -> dict[str, float]:
    """By file, the modification time of each of the stage's layers that has one."""
    found = {}
    for layer in stage.GetUsedLayers():
        path = layer.realPath
        if path and os.path.exists(path):
            found[path] = os.path.getmtime(path)
    return found


def _redraw() -> None:
    window_manager: Any = bpy.context.window_manager
    if window_manager is None:
        return
    for window in window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _frame_all(select: bool) -> None:
    """Frame the display in each 3D view, making Source Select its active tool with `select`."""
    context: Any = bpy.context  # its window manager is never None in a windowed Blender
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                region = next(r for r in area.regions if r.type == "WINDOW")
                with context.temp_override(window=window, area=area, region=region):
                    if select:
                        bpy.ops.wm.tool_set_by_id(name=select_tool.PROSCENIUM_TT_source_select.bl_idname)
                    bpy.ops.view3d.view_all()


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", nargs="?", default=os.environ.get("PROSCENIUM_DEMO_SCENE") or SCENE)
    parser.add_argument("--time", type=float, help="the time code to show (default: the stage's start)")
    parser.add_argument("--follow", action="store_true", help="synchronize at each frame's time code too")
    parser.add_argument("--select", action="store_true", help="select USD prims with Source Select")
    args = parser.parse_args(argv)
    if not args.scene:
        parser.error("no scene: pass one after --, set PROSCENIUM_DEMO_SCENE, or set SCENE in this file")
    start(Path(args.scene).expanduser().resolve(), args.time, args.follow, args.select)


main(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
