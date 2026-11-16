"""The Bounds Comparison Contract's check (testing/acceptance.md#bounds-comparison-contract), for M7's display.

The check reuses decisions made elsewhere (ABND-02): each copy's participation in each destination comes from the plan
(planned_copies), its source entity from the plan's correspondence, and its world transform, usable bounds, and kind
from USD's own APIs, under the spec's coordinate conversion (conversion_correction). It decides nothing itself.

What it compares (model_bounds_mismatches):

- Each prim whose kind is a model kind, once per drawn copy: inside native instances, at each instance-proxy path
  (ABND-03). Its display box in a destination is the box of every vertex displayed there for it or its descendants, in
  world space; its expected box the box of their usable bounds' corners under USD's local-to-world transform and the
  conversion, boxed after they are transformed (ABND-04).
- Each copy with usable bounds, corner by corner: its eight displayed vertices against its bounds' corners under its
  world transform, in the same order (ABND-07).
- Markers and content without usable bounds are on neither side; a model with nothing compared in a destination
  expects no displayed vertices there (ABND-08).
- Every face, and every corner coordinate, within 1e-6 + 1e-5 x m in Blender world units, m the largest absolute
  coordinate of the expected box or corners (ABND-09).

M7 draws a mesh as a box of its extent's corners, so a mesh copy is compared as the contract compares a placeholder,
by its usable bounds' corners: its authored extent, else USD's computed one (with the user, 2026-11-11). Comparing a
mesh's evaluated points is M8's, once it draws them. A copy with no prim of its own, a point instancer's, has no bounds
to read here, so its corners aren't compared; no fixture's model holds one in M7, and the check raises if a model does,
rather than guess.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pxr import Gf, Kind, Sdf, Usd, UsdGeom

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from proscenium.core import _core

XYZ = tuple[float, float, float]


class Destination(StrEnum):
    VIEWPORT = "viewport"
    RENDER = "render"


@dataclass(frozen=True)
class PlannedCopy:
    """A drawn copy as the plan decides it: its source entity and where it displays."""

    source_path: str  # an instance-proxy path inside native instances
    visible_in_viewport: bool
    visible_in_render: bool

    def displays_in(self, destination: Destination) -> bool:
        return self.visible_in_viewport if destination is Destination.VIEWPORT else self.visible_in_render


@dataclass(frozen=True)
class DisplayedCopy:
    """A drawn copy as the display shows it: its source entity, where it's shown, and its vertices in world space."""

    source_path: str
    visible_in_viewport: bool
    visible_in_render: bool
    world_vertices: tuple[XYZ, ...]  # in Blender world units; none for a marker

    def displays_in(self, destination: Destination) -> bool:
        return self.visible_in_viewport if destination is Destination.VIEWPORT else self.visible_in_render


def planned_copies(plan: _core.Plan) -> list[PlannedCopy]:
    """The plan's drawn copies, in its order."""
    with memoryview(plan.copy_visible_in_viewport) as viewport, memoryview(plan.copy_visible_in_render) as render:
        shown = list(zip(viewport.tolist(), render.tolist(), strict=True))
    return [PlannedCopy(e.source_path, bool(shown[i][0]), bool(shown[i][1])) for i, e in enumerate(plan.correspondence)]


def conversion_correction(stage: Usd.Stage, conversion: bool, unit_scale: float) -> Gf.Matrix4d:
    """The spec's correction C in USD's row-vector convention, so a world matrix W displays as W * C.

    transforms.md#coordinate-conversion: the identity with conversion off; else a scale of metersPerUnit over the target
    scene's unit scale, then +90 degrees about X for a Y-up stage.
    """
    if not conversion:
        return Gf.Matrix4d(1.0)
    scale = UsdGeom.GetStageMetersPerUnit(stage) / unit_scale
    correction = Gf.Matrix4d(1.0).SetScale(Gf.Vec3d(scale, scale, scale))
    if UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y:
        correction = correction * Gf.Matrix4d(1.0).SetRotate(Gf.Rotation(Gf.Vec3d(1, 0, 0), 90.0))
    return correction


def usable_bounds(prim: Usd.Prim, time: Usd.TimeCode) -> tuple[XYZ, XYZ] | None:
    """A gprim's usable bounds as M7 draws it, local: its authored extent, else USD's computed one, else none.

    USD computes a mesh's from its points, an implicit shape's from its parameters, and a curve's or points' from
    theirs (visibility.md#models-and-unsupported-content, MODEL-04); a volume has none without an authored extent.
    """
    boundable = UsdGeom.Boundable(prim)
    extent = boundable.GetExtentAttr()
    found = (
        extent.Get(time) if extent.HasAuthoredValue() else UsdGeom.Boundable.ComputeExtentFromPlugins(boundable, time)
    )
    if not found or len(found) != 2:
        return None
    low, high = found
    return (low[0], low[1], low[2]), (high[0], high[1], high[2])


def corners(low: Sequence[float], high: Sequence[float]) -> list[XYZ]:
    """The box's eight corners, in the application layer's order: x outermost, then y, then z."""
    return [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]


def tolerance(expected: Iterable[XYZ]) -> float:
    """1e-6 + 1e-5 x m, m the largest absolute coordinate of what's expected."""
    return 1e-6 + 1e-5 * max((abs(c) for point in expected for c in point), default=0.0)


@dataclass(frozen=True)
class _ExpectedCopy:
    planned: PlannedCopy
    world_corners: tuple[XYZ, ...]  # its usable bounds' corners in world space; none without usable bounds
    has_prim: bool  # False for a point instancer's copy, whose bounds aren't read here


def _expected_copies(
    stage: Usd.Stage, time: Usd.TimeCode, planned: Sequence[PlannedCopy], correction: Gf.Matrix4d
) -> dict[str, _ExpectedCopy]:
    cache = UsdGeom.XformCache(time)
    found = {}
    for copy in planned:
        prim = stage.GetPrimAtPath(copy.source_path)
        if not prim.IsValid():  # a point instancer's copy
            found[copy.source_path] = _ExpectedCopy(copy, (), has_prim=False)
            continue
        bounds = usable_bounds(prim, time)
        world = cache.GetLocalToWorldTransform(prim) * correction
        shown = () if bounds is None else tuple(world_point(world, c) for c in corners(*bounds))
        found[copy.source_path] = _ExpectedCopy(copy, shown, has_prim=True)
    return found


def models(stage: Usd.Stage) -> list[str]:
    """Each prim whose kind is a model kind, once per drawn copy: at each instance-proxy path inside instances."""
    found = []
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        kind = Usd.ModelAPI(prim).GetKind()
        if kind and Kind.Registry.IsA(kind, Kind.Tokens.model):
            found.append(str(prim.GetPath()))
    return found


def model_bounds_mismatches(
    stage: Usd.Stage,
    time: Usd.TimeCode,
    planned: Sequence[PlannedCopy],
    displayed: Iterable[DisplayedCopy],
    correction: Gf.Matrix4d,
) -> list[str]:
    """Where the display's bounds differ from USD's under the contract, each said in a line; none when they match.

    planned is the plan's copies, displayed what the display shows of them, and correction the conversion's.
    """
    expected = _expected_copies(stage, time, planned, correction)
    shown = {copy.source_path: copy for copy in displayed}
    problems = []
    for source, copy in expected.items():
        display = shown.get(source)
        if not copy.has_prim:
            continue
        if display is None:
            problems.append(f"{source}: not displayed")
        elif copy.world_corners:
            problems += _corner_mismatches(source, copy.world_corners, display.world_vertices)
        elif display.world_vertices:
            problems.append(f"{source}: displays vertices without usable bounds")
    for model in models(stage):
        root = Sdf.Path(model)
        inside = [s for s in expected if Sdf.Path(s).HasPrefix(root)]
        if not all(expected[s].has_prim for s in inside):
            raise NotImplementedError(f"{model} holds a point instancer's copies, whose bounds the check doesn't read")
        for destination in Destination:
            want = [
                c for s in inside if expected[s].planned.displays_in(destination) for c in expected[s].world_corners
            ]
            have = [
                v for s in inside if s in shown and shown[s].displays_in(destination) for v in shown[s].world_vertices
            ]
            problems += _box_mismatches(f"{model} in the {destination}", want, have)
    return problems


def _corner_mismatches(source: str, want: Sequence[XYZ], have: Sequence[XYZ]) -> list[str]:
    if len(have) != len(want):
        return [f"{source}: {len(have)} vertices displayed, against its box's {len(want)} corners"]
    limit = tolerance(want)
    return [
        f"{source}: corner {i} at {h}, expected {w}"
        for i, (w, h) in enumerate(zip(want, have, strict=True))
        if any(abs(a - b) > limit for a, b in zip(w, h, strict=True))
    ]


def _box_mismatches(label: str, want: Sequence[XYZ], have: Sequence[XYZ]) -> list[str]:
    if not want:
        return [f"{label}: {len(have)} vertices displayed with nothing compared"] if have else []
    if not have:
        return [f"{label}: nothing displayed"]
    expected, display = _box(want), _box(have)
    if not all(math.isfinite(c) for bound in expected for c in bound):
        return []  # isn't compared: its classification is checked instead
    limit = tolerance(expected)
    faces = [
        (e, d)
        for e_bound, d_bound in zip(expected, display, strict=True)
        for e, d in zip(e_bound, d_bound, strict=True)
    ]
    if any(abs(e - d) > limit for e, d in faces):
        return [f"{label}: display box {display}, expected {expected}"]
    return []


def _box(points: Sequence[XYZ]) -> tuple[XYZ, XYZ]:
    low = tuple(min(p[i] for p in points) for i in range(3))
    high = tuple(max(p[i] for p in points) for i in range(3))
    return (low[0], low[1], low[2]), (high[0], high[1], high[2])


def world_point(matrix: Gf.Matrix4d, point: XYZ) -> XYZ:
    """Point under matrix, in USD's row-vector convention."""
    v = matrix.Transform(Gf.Vec3d(*point))
    return (float(v[0]), float(v[1]), float(v[2]))  # ty: ignore[invalid-argument-type] - Vec3d's items are floats
