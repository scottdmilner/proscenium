"""The source-info filter's facts, through the minimal plan, on F-UNSUPPORTED-CONTENT (M6 plan, B2).

Curves and points without an authored extent show USD's computed one, and a HermiteCurves, which Hydra doesn't
image, still gets a placeholder with its transform and authored extent (case "placeholders", SNAP-17, MODEL-04).
Stage edits and time changes reach both. Expected values come from the fixture, or from UsdGeom after an edit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from pxr import Gf, Usd, UsdGeom, Vt

from fixtures import evaluation
from proscenium.core import _core

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

CONTEXT = _core.PlanningContext(unit_scale=1.0, representation_version=1)
COMBED, DOTS, TANGENTS = "/World/Combed", "/World/Dots", "/World/Tangents"


@pytest.fixture
def unsupported(tmp_path: Path) -> Iterator[evaluation.UnsupportedScene]:
    with evaluation.unsupported_content(tmp_path) as scene:
        yield scene


def _placeholders(stage: Usd.Stage, time: float) -> dict[str, _core.Placeholder]:
    chain = _core.SceneIndexChain(stage)
    try:
        plan = _core.plan(chain.capture(Usd.TimeCode(time)), CONTEXT)
    finally:
        chain.release()
    return _shown(plan)


def _shown(plan: _core.Plan) -> dict[str, _core.Placeholder]:
    objects = {c.element: c.source for c in plan.correspondence}
    return {objects[p.object]: p for p in plan.placeholders}


XYZ = tuple[float, float, float]


def _xyz(v: Gf.Vec3d | Sequence[float]) -> XYZ:
    return cast("XYZ", tuple(float(c) for c in cast("Sequence[float]", v)))


def _corners(world: Gf.Matrix4d, low: XYZ, high: XYZ) -> list[XYZ]:
    return [
        _xyz(world.Transform(Gf.Vec3d(x, y, z)))
        for x in (low[0], high[0])
        for y in (low[1], high[1])
        for z in (low[2], high[2])
    ]


def _assert_box(placeholder: _core.Placeholder, world: Gf.Matrix4d, low: Gf.Vec3d, high: Gf.Vec3d) -> None:
    """The placeholder's corners are the expected ones, within the bounds comparison contract's tolerance."""
    bounds = list(placeholder.bounds)
    assert len(bounds) == 6
    expected = _corners(world, _xyz(low), _xyz(high))
    tolerance = 1e-6 + 1e-5 * max(abs(c) for corner in expected for c in corner)
    for shown, corner in zip(_corners(placeholder.world, _xyz(bounds[:3]), _xyz(bounds[3:])), expected, strict=True):
        assert all(abs(a - b) <= tolerance for a, b in zip(shown, corner, strict=True)), (shown, corner)


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
    shown = _placeholders(unsupported.stage, 0.0)
    for path, expected in unsupported.placeholders.items():
        if expected.type_name == "PointInstancer":
            continue  # the minimal planner draws gprims only; Phase C plans point instancers
        assert path in shown, path
        if expected.bounds is None:  # a marker
            assert len(shown[path].bounds) == 0, path
        else:
            _assert_box(shown[path], expected.world, *expected.bounds)


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
        shown = _shown(_core.plan(chain.capture(Usd.TimeCode(0.0)), CONTEXT))
    finally:
        chain.release()
    for path in (COMBED, DOTS, TANGENTS):
        _assert_box(shown[path], *_usd_box(stage, path, 0.0))
    # The edits reached the plan, so the checks above could fail.
    assert shown[TANGENTS].world == Gf.Matrix4d().SetScale(2) * Gf.Matrix4d().SetTranslate((9, 5, 0))


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
        shown = {t: _shown(_core.plan(chain.capture(Usd.TimeCode(t)), CONTEXT)) for t in (0.0, 10.0)}
    finally:
        chain.release()
    for time, placeholders in shown.items():
        for path in (COMBED, TANGENTS):
            _assert_box(placeholders[path], *_usd_box(stage, path, time))
    assert shown[0.0][TANGENTS].world != shown[10.0][TANGENTS].world  # the checks above could fail
    assert list(shown[0.0][COMBED].bounds) != list(shown[10.0][COMBED].bounds)
