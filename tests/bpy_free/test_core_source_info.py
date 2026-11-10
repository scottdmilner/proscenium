"""The source-info filter's facts, through the minimal plan, on F-UNSUPPORTED-CONTENT (M6 plan, B2).

Curves and points without an authored extent show USD's computed one, and a HermiteCurves, which Hydra doesn't
image, still gets a placeholder with its transform and authored extent (case "placeholders", SNAP-17, MODEL-04).
Stage edits and time changes reach both. Expected values come from the fixture, or from UsdGeom after an edit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Usd, UsdGeom, Vt

from fixtures import evaluation
from proscenium.core import _core

from .plan_checks import CONTEXT, SETTINGS, assert_box, copies, plan_at

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

COMBED, DOTS, TANGENTS = "/World/Combed", "/World/Dots", "/World/Tangents"


@pytest.fixture
def unsupported(tmp_path: Path) -> Iterator[evaluation.UnsupportedScene]:
    with evaluation.unsupported_content(tmp_path) as scene:
        yield scene


def _usd_box(stage: Usd.Stage, path: str, time: float) -> tuple[Gf.Matrix4d, Gf.Vec3d, Gf.Vec3d]:
    """USD's world transform of `path` at `time`, and its usable bounds: its authored extent, else its computed one."""
    prim = stage.GetPrimAtPath(path)
    code = Usd.TimeCode(time)
    boundable = UsdGeom.Boundable(prim)
    extent = boundable.GetExtentAttr().Get(code) or UsdGeom.Boundable.ComputeExtentFromPlugins(boundable, code)
    assert extent is not None
    world = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(code)
    return world, Gf.Vec3d(extent[0]), Gf.Vec3d(extent[1])


def test_placeholders_show_authored_or_computed_bounds(unsupported: evaluation.UnsupportedScene) -> None:
    shown = copies(plan_at(unsupported.stage, 0.0))
    for path, expected in unsupported.placeholders.items():
        assert path in shown, path
        assert shown[path].geometry_index == -1, path  # not a mesh
        if expected.local_bounds is None:  # a marker
            assert shown[path].placeholder_bounds_index == -1, path
        else:
            assert shown[path].placeholder_bounds_index >= 0, path
            assert_box(shown[path], expected.world_matrix, *expected.local_bounds)


def test_stage_edits_reach_computed_extents_and_unimaged_prims(unsupported: evaluation.UnsupportedScene) -> None:
    stage = unsupported.stage
    chain = _core.SceneIndexChain(stage)
    try:
        chain.capture(Usd.TimeCode(0.0))
        UsdGeom.PointBased(stage.GetPrimAtPath(COMBED)).GetPointsAttr().Set(Vt.Vec3fArray([(0, 0, 0), (0, 0, 4)]))
        UsdGeom.Points(stage.GetPrimAtPath(DOTS)).GetWidthsAttr().Set(Vt.FloatArray([1.0, 1.0]))
        tangents = UsdGeom.Xformable(stage.GetPrimAtPath(TANGENTS))
        tangents.GetPrim().GetAttribute("xformOp:translate").Set(Gf.Vec3d(9, 5, 0))
        tangents.AddScaleOp().Set(Gf.Vec3f(2, 2, 2))  # a new op, so a new op order
        shown = copies(_core.plan(chain.capture(Usd.TimeCode(0.0)), SETTINGS, CONTEXT))
    finally:
        chain.release()
    for path in (COMBED, DOTS, TANGENTS):
        assert_box(shown[path], *_usd_box(stage, path, 0.0))
    # The edits reached the plan, so the checks above could fail.
    assert shown[TANGENTS].world_matrix == Gf.Matrix4d().SetScale(2) * Gf.Matrix4d().SetTranslate((9, 5, 0))


def test_time_changes_reach_computed_extents_and_unimaged_prims(unsupported: evaluation.UnsupportedScene) -> None:
    stage = unsupported.stage
    points = UsdGeom.PointBased(stage.GetPrimAtPath(COMBED)).GetPointsAttr()
    points.Set(Vt.Vec3fArray([(0, 0, 0), (0, 0, 2)]), Usd.TimeCode(0.0))
    points.Set(Vt.Vec3fArray([(0, 0, 0), (0, 3, 2)]), Usd.TimeCode(10.0))
    translate = stage.GetPrimAtPath(TANGENTS).GetAttribute("xformOp:translate")
    translate.Set(Gf.Vec3d(9, 0, 0), Usd.TimeCode(0.0))
    translate.Set(Gf.Vec3d(9, 0, 4), Usd.TimeCode(10.0))
    chain = _core.SceneIndexChain(stage)
    try:
        # One chain, moved from one time code to the next, as a cache call moves it.
        shown = {t: copies(_core.plan(chain.capture(Usd.TimeCode(t)), SETTINGS, CONTEXT)) for t in (0.0, 10.0)}
    finally:
        chain.release()
    for time, at in shown.items():
        for path in (COMBED, TANGENTS):
            assert_box(at[path], *_usd_box(stage, path, time))
    assert shown[0.0][TANGENTS].world_matrix != shown[10.0][TANGENTS].world_matrix  # the checks above could fail
    assert list(shown[0.0][COMBED].local_bounds) != list(shown[10.0][COMBED].local_bounds)
