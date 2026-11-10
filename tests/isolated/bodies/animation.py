"""Isolated body: M4 Phase E, time-sampled data: frames captured over a range by the bridge's frames.py (E1).

Runs in a fresh process (isolated/harness.py); see tests/isolated/test_frames.py.
"""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy  # noqa: F401 - the wheel's pxr
from pxr import Usd

BRIDGE = Path(__file__).resolve().parents[3] / "tools/feasibility/hydra_bridge"
SCENES = ("animation.usda", "frames.usda")  # frames.usda sublayers M1b's animation case


def _summary(record: dict[str, Any]) -> list[Any]:
    matrix = record["matrix"]
    rows = [[round(matrix[row][col], 6) for col in range(4)] for row in range(4)]
    return [record["source"], list(record["instance_context"]), record["viewport"], record["render"], rows]


def capture(module_dir: str, dest: str, times: list[float]) -> dict[str, Any]:
    """Each track's objects, what varies along it, and its record at each frame; and each frame's fresh plan.

    Records are summarized as (source, context, viewport, render, matrix).
    """
    sys.path[:0] = [str(BRIDGE), module_dir]
    native = importlib.import_module("_hydra_bridge")
    frames = importlib.import_module("frames")
    for name in SCENES:
        shutil.copy(BRIDGE / "cases" / name, dest)
    stage = Usd.Stage.Open(str(Path(dest) / "frames.usda"))
    bridge = native.Bridge(stage)
    try:
        captured = frames.capture_frames(native, bridge, times)
        tracks = []
        for key, objects in captured.object_indices_by_track.items():
            records = [captured.record(key, frame) for frame in range(len(times))]
            tracks.append(
                {
                    "key": [*key[:2], key[2]],
                    "objects": objects,
                    "varying": sorted(captured.varying_aspects_by_track[key]),
                    "records": [None if r is None else _summary(r) for r in records],
                }
            )
        fresh = []
        for time in times:
            other = native.Bridge(stage)
            fresh.append([_summary(o) for o in native.build_plan(other.capture(time)).objects])
            other.release()
        return {"tracks": tracks, "frames": fresh}
    finally:
        bridge.release()
