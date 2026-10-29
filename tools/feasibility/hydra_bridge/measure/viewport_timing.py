"""Viewport frame time in a windowed Blender (M4 Phase D), after a synchronization.

Each shading mode, Solid (Workbench) and Material Preview (EEVEE), is timed on the 3D view of the startup
layout, framed on everything, with nothing selected:
- the first frame, which builds the draw caches and starts any shader compilation;
- the wait until shader compilation ends, redrawing meanwhile;
- the frame time while orbiting: each frame turns the view a degree about Z and redraws. Turning the view
  restarts the viewport's sample accumulation, so every frame draws the scene, as navigation does; a still view
  would only redisplay its converged samples. Each repeat times FRAMES frames, so the GPU work of earlier frames
  is in the time once its queue fills. Each frame redraws the window with a swap, which waits for the display's
  refresh, so no frame is shorter than one refresh interval (8.3 ms at 120 Hz): a frame at that floor can't be
  told from a faster one. Redrawing the 3D view alone, without a swap, measured no drawing at all (0.02 ms on
  30,001 objects, ad hoc), so it isn't timed.
"""

from __future__ import annotations

import math
import statistics
import time
from typing import Any

import bpy
from mathutils import Quaternion

SHADINGS = {"solid": "SOLID", "material preview": "MATERIAL"}
FRAMES = 20  # per timed repeat
REPEATS = 5
WARMUP = 5  # frames before the timed repeats
COMPILE_TIMEOUT = 1800.0  # s
TURN = Quaternion((0.0, 0.0, 1.0), math.radians(1.0))


def measure() -> dict[str, Any]:
    """Each shading mode's first frame, shader compilation, and orbiting frame time, and the view's size."""
    window, area, region = _view()
    space: Any = area.spaces.active
    view: Any = space.region_3d
    view_layer: Any = bpy.context.view_layer  # never None in a running Blender
    for obj in view_layer.objects:
        obj.select_set(False)
    timings: dict[str, Any] = {}
    override = bpy.context.temp_override(window=window, area=area, region=region)
    with override:  # ty: ignore[invalid-context-manager] - the stubs don't declare it a context manager
        bpy.ops.view3d.view_all(center=False)

        def frame() -> None:
            view.view_rotation = TURN @ view.view_rotation
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)

        for name, shading in SHADINGS.items():
            space.shading.type = shading
            start = time.perf_counter()
            frame()
            timings[f"{name}: first frame"] = time.perf_counter() - start
            start = time.perf_counter()
            while bpy.app.is_job_running("SHADER_COMPILATION"):
                if time.perf_counter() - start > COMPILE_TIMEOUT:
                    raise TimeoutError(f"{name}: shaders still compiling after {COMPILE_TIMEOUT} s")
                frame()
            timings[f"{name}: until shaders compiled"] = time.perf_counter() - start
            for _ in range(WARMUP):
                frame()
            per_frame = []
            for _ in range(REPEATS):
                start = time.perf_counter()
                for _ in range(FRAMES):
                    frame()
                per_frame.append((time.perf_counter() - start) / FRAMES)
            timings[f"{name}: orbiting frame"] = {
                "median": statistics.median(per_frame),
                "min": min(per_frame),
                "max": max(per_frame),
                "repeats": REPEATS,
            }
    sizes = {
        "view pixels": [region.width, region.height],
        "window pixels": [window.width, window.height],
        "frames per repeat": FRAMES,
        "gpu": f"{bpy.app.build_platform.decode()} {_gpu()}",
    }
    return {"timings": timings, "sizes": sizes}


def _view() -> tuple[Any, Any, Any]:
    """The startup layout's 3D view: its window, area, and main region."""
    manager: Any = bpy.context.window_manager  # never None in a running Blender
    for window in manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                return window, area, next(r for r in area.regions if r.type == "WINDOW")
    raise RuntimeError("no 3D view: the viewport mode needs a windowed Blender")


def _gpu() -> str:
    import gpu

    return f"{gpu.platform.vendor_get()} {gpu.platform.renderer_get()} ({gpu.platform.backend_type_get()})"
