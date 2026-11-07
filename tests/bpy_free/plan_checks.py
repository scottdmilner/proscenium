"""Checks of the core's plans against expected values: drawn copies by source, and their corners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from pxr import Gf, Usd

from proscenium.core import _core

if TYPE_CHECKING:
    from collections.abc import Sequence

CONTEXT = _core.PlanningContext(unit_scale=1.0, representation_version=1)

XYZ = tuple[float, float, float]


@dataclass(frozen=True)
class Copy:
    """A drawn copy as the plan's copy table gives it."""

    object: int  # in resources
    bounds_mesh: int  # in resources: the object's one use
    world: Gf.Matrix4d  # USD's row-vector convention
    geometry: int  # in geometries; -1 for none
    placeholder: int  # in placeholder_bounds; -1 for none
    bounds: tuple[float, ...]  # local: its geometry's extent, else its placeholder's bounds; empty for none


def plan_at(stage: Usd.Stage, time: float) -> _core.Plan:
    """The plan of one capture at `time`, with the chain released."""
    chain = _core.SceneIndexChain(stage)
    try:
        return _core.plan(chain.capture(Usd.TimeCode(time)), CONTEXT)
    finally:
        chain.release()


def copies(plan: _core.Plan) -> dict[str, Copy]:
    """Each drawn copy by its source, read from the plan's copy table."""
    objects = memoryview(plan.copy_objects).tolist()
    worlds = memoryview(plan.copy_worlds).tolist()
    geometries = memoryview(plan.copy_geometries).tolist()
    placeholders = memoryview(plan.copy_placeholders).tolist()
    bounds = memoryview(plan.placeholder_bounds).tolist()
    extents = [tuple(memoryview(g.extent).tolist()) for g in plan.geometries]
    sources = {c.element: c.source for c in plan.correspondence}
    shown: dict[str, Copy] = {}
    for copy, (obj, geometry, placeholder) in enumerate(zip(objects, geometries, placeholders, strict=True)):
        if geometry >= 0:
            local = extents[geometry]
        else:
            local = tuple(bounds[6 * placeholder : 6 * placeholder + 6]) if placeholder >= 0 else ()
        (bounds_mesh,) = plan.resources[obj].uses
        world = Gf.Matrix4d(*worlds[16 * copy : 16 * copy + 16])  # row-major, USD's layout
        shown[sources[obj]] = Copy(obj, bounds_mesh, world, geometry, placeholder, local)
    return shown


def xyz(v: Gf.Vec3d | Sequence[float]) -> XYZ:
    return cast("XYZ", tuple(float(c) for c in cast("Sequence[float]", v)))


def corners(world: Gf.Matrix4d, low: XYZ, high: XYZ) -> list[XYZ]:
    return [
        xyz(world.Transform(Gf.Vec3d(x, y, z)))
        for x in (low[0], high[0])
        for y in (low[1], high[1])
        for z in (low[2], high[2])
    ]


def assert_box(copy: Copy, world: Gf.Matrix4d, low: Gf.Vec3d, high: Gf.Vec3d) -> None:
    """The copy's corners are the expected ones, within the bounds comparison contract's tolerance."""
    assert len(copy.bounds) == 6
    _assert_corners(
        corners(copy.world, xyz(copy.bounds[:3]), xyz(copy.bounds[3:])), corners(world, xyz(low), xyz(high))
    )


def assert_world(copy: Copy, world: Gf.Matrix4d) -> None:
    """The copy's world transform is `world`, compared by where each takes the unit cube's corners."""
    unit = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    _assert_corners(corners(copy.world, *unit), corners(world, *unit))


def _assert_corners(shown: list[XYZ], expected: list[XYZ]) -> None:
    # Each coordinate within 1e-6 + 1e-5 m, m the expected corners' largest absolute coordinate (acceptance.md).
    tolerance = 1e-6 + 1e-5 * max(abs(c) for corner in expected for c in corner)
    for at, corner in zip(shown, expected, strict=True):
        assert all(abs(a - b) <= tolerance for a, b in zip(at, corner, strict=True)), (at, corner)
