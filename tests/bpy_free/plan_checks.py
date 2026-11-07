"""Checks of the core's plans against expected values: placeholders' corners and copies by source."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pxr import Gf, Usd

from proscenium.core import _core

if TYPE_CHECKING:
    from collections.abc import Sequence

CONTEXT = _core.PlanningContext(unit_scale=1.0, representation_version=1)

XYZ = tuple[float, float, float]


def plan_at(stage: Usd.Stage, time: float) -> _core.Plan:
    """The plan of one capture at `time`, with the chain released."""
    chain = _core.SceneIndexChain(stage)
    try:
        return _core.plan(chain.capture(Usd.TimeCode(time)), CONTEXT)
    finally:
        chain.release()


def placeholders(plan: _core.Plan) -> dict[str, _core.Placeholder]:
    """Each placeholder by its copy's source."""
    objects = {c.element: c.source for c in plan.correspondence}
    return {objects[p.object]: p for p in plan.placeholders}


def xyz(v: Gf.Vec3d | Sequence[float]) -> XYZ:
    return cast("XYZ", tuple(float(c) for c in cast("Sequence[float]", v)))


def corners(world: Gf.Matrix4d, low: XYZ, high: XYZ) -> list[XYZ]:
    return [
        xyz(world.Transform(Gf.Vec3d(x, y, z)))
        for x in (low[0], high[0])
        for y in (low[1], high[1])
        for z in (low[2], high[2])
    ]


def assert_box(placeholder: _core.Placeholder, world: Gf.Matrix4d, low: Gf.Vec3d, high: Gf.Vec3d) -> None:
    """The placeholder's corners are the expected ones, within the bounds comparison contract's tolerance."""
    bounds = list(placeholder.bounds)
    assert len(bounds) == 6
    _assert_corners(corners(placeholder.world, xyz(bounds[:3]), xyz(bounds[3:])), corners(world, xyz(low), xyz(high)))


def assert_world(placeholder: _core.Placeholder, world: Gf.Matrix4d) -> None:
    """The placeholder's world transform is `world`, compared by where each takes the unit cube's corners."""
    unit = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    _assert_corners(corners(placeholder.world, *unit), corners(world, *unit))


def _assert_corners(shown: list[XYZ], expected: list[XYZ]) -> None:
    # Each coordinate within 1e-6 + 1e-5 m, m the expected corners' largest absolute coordinate (acceptance.md).
    tolerance = 1e-6 + 1e-5 * max(abs(c) for corner in expected for c in corner)
    for at, corner in zip(shown, expected, strict=True):
        assert all(abs(a - b) <= tolerance for a, b in zip(at, corner, strict=True)), (at, corner)
