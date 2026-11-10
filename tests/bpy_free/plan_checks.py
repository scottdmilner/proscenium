"""Checks of the core's plans against expected values: drawn copies by source, and their corners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from pxr import Gf, Usd

from fixtures import evaluation
from proscenium.core import _core

if TYPE_CHECKING:
    from collections.abc import Sequence

CONTEXT = _core.PlanningContext(unit_scale=1.0, representation_version=1)
SETTINGS = _core.PlanSettings(evaluation.VIEWPORT_PURPOSES, evaluation.RENDER_PURPOSES)  # the defaults

XYZ = tuple[float, float, float]


@dataclass(frozen=True)
class PlannedDrawnCopy:
    """A drawn copy as the plan's copy table gives it."""

    object_resource_index: int  # in resources
    bounds_mesh_resource_index: int | None  # in resources: one of the object's uses; None for an empty marker's
    world_matrix: Gf.Matrix4d  # USD's row-vector convention
    geometry_index: int  # in geometries; -1 for none
    placeholder_bounds_index: int  # in placeholder_bounds; -1 for none
    local_bounds: tuple[float, ...]  # local: its geometry's extent, else its placeholder's bounds; empty for none
    visible_in_viewport: bool  # displays in the viewport
    visible_in_render: bool  # displays in the final render
    # A sheared copy's shear parent's world matrix, and its object's basis.
    shear_transform_split: tuple[Gf.Matrix4d, Gf.Matrix4d] | None


def plan_at(stage: Usd.Stage, time: float, settings: _core.PlanSettings = SETTINGS) -> _core.Plan:
    """The plan of one capture at `time`, with the chain released."""
    chain = _core.SceneIndexChain(stage)
    try:
        return _core.plan(chain.capture(Usd.TimeCode(time)), settings, CONTEXT)
    finally:
        chain.release()


def copies(plan: _core.Plan) -> dict[str, PlannedDrawnCopy]:
    """Each drawn copy by its source, read from the plan's copy table."""
    objects = memoryview(plan.copy_object_resource_indices).tolist()
    worlds = memoryview(plan.copy_world_matrices).tolist()
    geometries = memoryview(plan.copy_geometry_indices).tolist()
    placeholders = memoryview(plan.copy_placeholder_bounds_indices).tolist()
    bounds = memoryview(plan.placeholder_bounds).tolist()
    viewport, render = (
        memoryview(plan.copy_visible_in_viewport).tolist(),
        memoryview(plan.copy_visible_in_render).tolist(),
    )
    shears = memoryview(plan.copy_shear_split_indices).tolist()
    parent_worlds = memoryview(plan.shear_parent_world_matrices).tolist()
    bases = memoryview(plan.shear_object_basis_matrices).tolist()
    extents = [tuple(memoryview(g.extent).tolist()) for g in plan.geometries]
    sources = {c.object_resource_index: c.source_path for c in plan.correspondence}
    resources = plan.resources
    shown: dict[str, PlannedDrawnCopy] = {}
    for copy, (obj, geometry, placeholder) in enumerate(zip(objects, geometries, placeholders, strict=True)):
        if geometry >= 0:
            local = extents[geometry]
        else:
            local = tuple(bounds[6 * placeholder : 6 * placeholder + 6]) if placeholder >= 0 else ()
        bounds_mesh = next(
            (u for u in resources[obj].dependency_resource_indices if resources[u].role == "bounds mesh"), None
        )
        shear = shears[copy]
        split = None if shear < 0 else (_matrix(parent_worlds, shear), _matrix(bases, shear))
        shown_in = bool(viewport[copy]), bool(render[copy])
        shown[sources[obj]] = PlannedDrawnCopy(
            obj, bounds_mesh, _matrix(worlds, copy), geometry, placeholder, local, *shown_in, split
        )
    return shown


def _matrix(matrices: Sequence[float], index: int) -> Gf.Matrix4d:
    return Gf.Matrix4d(*matrices[16 * index : 16 * index + 16])  # row-major, USD's layout


def xyz(v: Gf.Vec3d | Sequence[float]) -> XYZ:
    return cast("XYZ", tuple(float(c) for c in cast("Sequence[float]", v)))


def corners(world: Gf.Matrix4d, low: XYZ, high: XYZ) -> list[XYZ]:
    return [
        xyz(world.Transform(Gf.Vec3d(x, y, z)))
        for x in (low[0], high[0])
        for y in (low[1], high[1])
        for z in (low[2], high[2])
    ]


def assert_box(copy: PlannedDrawnCopy, world: Gf.Matrix4d, low: Gf.Vec3d, high: Gf.Vec3d) -> None:
    """The copy's corners are the expected ones, within the bounds comparison contract's tolerance."""
    assert len(copy.local_bounds) == 6
    _assert_corners(
        corners(copy.world_matrix, xyz(copy.local_bounds[:3]), xyz(copy.local_bounds[3:])),
        corners(world, xyz(low), xyz(high)),
    )


def assert_world(copy: PlannedDrawnCopy, world: Gf.Matrix4d) -> None:
    """The copy's world transform is `world`, compared by where each takes the unit cube's corners."""
    unit = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    _assert_corners(corners(copy.world_matrix, *unit), corners(world, *unit))


def _assert_corners(shown: list[XYZ], expected: list[XYZ]) -> None:
    # Each coordinate within 1e-6 + 1e-5 m, m the expected corners' largest absolute coordinate (acceptance.md).
    tolerance = 1e-6 + 1e-5 * max(abs(c) for corner in expected for c in corner)
    for at, corner in zip(shown, expected, strict=True):
        assert all(abs(a - b) <= tolerance for a, b in zip(at, corner, strict=True)), (at, corner)
