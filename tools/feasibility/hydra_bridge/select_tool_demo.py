"""Install the source selection tool (select_tool.py) over a USD scene, in a windowed Blender (M4 Phase F, Q4).

    blender --python tools/feasibility/hydra_bridge/select_tool_demo.py -- SCENE.usd [--minimum N] [--time T]

Builds Phase D's batched display of the scene (batched_display.py, copies alike but for placement batched in groups
of at
least N, 3 by default) at time code T, its start by default, and makes Source Select the 3D view's active tool.
Expects the bridge built by build.py in build/hydra-bridge/. Nothing is saved.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "build/hydra-bridge")]

import _hydra_bridge as native  # noqa: E402  # ty: ignore[unresolved-import] - built into build/hydra-bridge
import batched_display  # noqa: E402
import bpy  # noqa: E402
import select_tool  # noqa: E402
from pxr import Usd  # noqa: E402


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene")
    parser.add_argument("--minimum", type=int, default=3)
    parser.add_argument("--time", type=float)
    args = parser.parse_args(argv)
    bpy.ops.wm.read_factory_settings(use_empty=False)
    bpy.data.batch_remove(list(bpy.data.objects))  # the startup cube, camera, and light
    stage = Usd.Stage.Open(args.scene)
    time = stage.GetStartTimeCode() if args.time is None else args.time
    bridge = native.Bridge(stage)
    plan = native.build_plan(bridge.capture(time))
    scene: Any = bpy.context.scene
    collection = bpy.data.collections.new(Path(args.scene).stem)
    scene.collection.children.link(collection)
    display = batched_display.apply_batched(plan, collection, args.minimum)
    interaction = native.SourceSelectionResolver(stage, plan)
    view_layer: Any = bpy.context.view_layer  # never None in a running Blender
    select_tool.register(
        select_tool.Session(
            interaction,
            display,
            view_layer,
            collection,
            retained_source_objects=(stage, bridge, plan),
            stage=stage,
            time_code=time,
        )
    )
    bpy.app.timers.register(_activate, first_interval=0.5)
    print(
        f"Source Select over {plan.object_count} copies: {len(display.batches)} batches, "
        f"{len(display.objects)} objects kept as objects"
    )


def _activate() -> None:
    """Make Source Select the active tool of each 3D view, and frame the display."""
    context: Any = bpy.context  # its window manager is never None in a windowed Blender
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                region = next(r for r in area.regions if r.type == "WINDOW")
                with context.temp_override(window=window, area=area, region=region):
                    bpy.ops.wm.tool_set_by_id(name=select_tool.PROSCENIUM_TT_source_select.bl_idname)
                    bpy.ops.view3d.view_all()


main(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
