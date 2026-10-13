"""Implicit shape -> mesh: a mesh for every shape, the approximation diagnostic for inexact ones, none for exact."""

from __future__ import annotations

import math
from itertools import product
from typing import Any

from pxr import Gf, UsdGeom

from . import oracle
from .harness import Case, codes

TIME = 1.0
EXACT = {"/World/Box", "/World/Floor"}
APPROXIMATED = {"/World/Ball", "/World/Spike", "/World/Pipe", "/World/Pill", "/World/Sheet"}
TOLERANCE = 1e-5
# Each approximated mesh's bounds must cover at least this fraction of USD's extent on every axis: a polygon
# inscribed in a circle covers cos(pi / segments) of it, about 0.95 for Hydra's ten segments.
COVERAGE = 0.9
AXES = {"X": 0, "Y": 1, "Z": 2}
CLOSED = APPROXIMATED - {"/World/Sheet"} | {"/World/Box"}


def run(case: Case) -> None:
    stage = case.open("implicit.usda")
    snapshot = case.native.Bridge(stage).capture(TIME)
    plan = case.native.build_plan(snapshot)
    by_source = {o["source"]: o for o in plan.objects}
    shapes = EXACT | APPROXIMATED

    case.check(
        "every implicit shape and the NURBS patch becomes a mesh",
        all(source in by_source and by_source[source]["mesh"] is not None for source in shapes),
        {s: by_source.get(s, {}).get("placeholder_type") for s in shapes},
    )
    diagnosed = {source for source in shapes if "approximated-surface" in codes(plan, source)}
    case.check("inexact shapes are diagnosed as approximated, exact ones are not", diagnosed == APPROXIMATED, diagnosed)
    wrong = [s for s in shapes if not oracle.close(by_source[s]["matrix"], oracle.world(stage, s, TIME))]
    case.check("world transforms match UsdGeom", not wrong, wrong)

    # USD computes each shape's local extent from its parameters (the NURBS patch's from its control points).
    spans = {}
    for source in sorted(shapes):
        extent = UsdGeom.Boundable.ComputeExtentFromPlugins(UsdGeom.Boundable(stage.GetPrimAtPath(source)), TIME)
        positions = plan.meshes[by_source[source]["mesh"]]["positions"]
        low, high = _bounds(positions)
        spans[source] = {"usd_extent": (tuple(extent[0]), tuple(extent[1])), "mesh_bounds": (low, high)}
    wrong = [s for s in EXACT if not _same_box(spans[s]["mesh_bounds"], spans[s]["usd_extent"])]
    case.check("exact shapes' meshes have exactly USD's extent", not wrong, {s: spans[s] for s in wrong})
    wrong = [s for s in APPROXIMATED if not _inside(spans[s]["mesh_bounds"], spans[s]["usd_extent"])]
    case.check("approximated meshes lie within USD's extent", not wrong, {s: spans[s] for s in wrong})
    case.findings["mesh bounds against USD extent"] = spans
    case.findings["subdivision schemes"] = {s: plan.meshes[by_source[s]["mesh"]]["subdivision_scheme"] for s in shapes}
    case.findings["face counts"] = {s: len(plan.meshes[by_source[s]["mesh"]]["face_offsets"]) for s in shapes}

    expected = {s: UsdGeom.Gprim(stage.GetPrimAtPath(s)).GetDoubleSidedAttr().Get() for s in shapes}
    planned = {s: plan.meshes[by_source[s]["mesh"]]["double_sided"] for s in shapes}
    case.check("doubleSided matches USD, schema fallbacks included", planned == expected, (planned, expected))
    hydra = {s: snapshot.prim(s)["double_sided"] for s in shapes}
    case.findings["doubleSided as Hydra reports it"] = hydra
    case.known_gap(
        "the implicit-surface filter loses a Cube's authored doubleSided = true (the source-info filter supplies it)",
        hydra["/World/Box"] is False and expected["/World/Box"] is True,
        hydra,
    )

    wrong = {}
    for source in EXACT:
        low, high = spans[source]["usd_extent"]
        corners = {_rounded(c) for c in product(*zip(low, high, strict=True))}
        vertices = {_rounded(p) for p in plan.meshes[by_source[source]["mesh"]]["positions"]}
        if vertices != corners:
            wrong[source] = (sorted(vertices), sorted(corners))
    case.check("exact shapes' vertices are exactly the corners of USD's extent", not wrong, wrong)
    wrong = {}
    for source in APPROXIMATED - {"/World/Sheet"}:
        prim = stage.GetPrimAtPath(source)
        off = [tuple(p) for p in plan.meshes[by_source[source]["mesh"]]["positions"] if not _on_surface(prim, p)]
        if off:
            wrong[source] = off[:5]
    case.check(
        "approximated shapes' vertices lie on USD's surface (sphere, cylinder, cone, capsule parameters)",
        not wrong,
        wrong,
    )
    wrong = {s: spans[s] for s in APPROXIMATED if not _covers(spans[s]["mesh_bounds"], spans[s]["usd_extent"])}
    case.check(f"approximated meshes span at least {COVERAGE:.0%} of USD's extent on every axis", not wrong, wrong)

    sheet = UsdGeom.NurbsPatch(stage.GetPrimAtPath("/World/Sheet"))
    control = [Gf.Vec3d(p) for p in sheet.GetPointsAttr().Get(TIME)]
    midpoint = _bezier_midpoint(control, sheet.GetUVertexCountAttr().Get(), sheet.GetVVertexCountAttr().Get())
    hull = _bounds(control)
    case.findings["NURBS patch midpoint against its mesh"] = {"surface": tuple(midpoint), "mesh": spans["/World/Sheet"]}
    # Accepted behavior, diagnosed as an approximation: the hull is a coarse but faithful display of the patch.
    case.check(
        "the NURBS patch is displayed as its control hull: mesh bounds equal the control points', above the surface",
        _same_box(spans["/World/Sheet"]["mesh_bounds"], hull) and midpoint[2] < hull[1][2] - 0.1,
        (spans["/World/Sheet"]["mesh_bounds"], hull, tuple(midpoint)),
    )

    created = case.apply_plan(plan)
    invalid = [s for s in shapes if _mesh(created[s]).validate()]
    case.check("Blender accepts every converted mesh unchanged", not invalid, invalid)
    # Local coordinates: every closed shape is centred on its origin, so an outward face points away from it.
    wrong = {}
    for source in CLOSED:
        polygons = _mesh(created[source]).polygons
        inward = [i for i, p in enumerate(polygons) if p.normal.dot(p.center) <= 0]
        if inward:
            wrong[source] = (len(inward), len(polygons))
    # The plane's normal is its +axis; the patch's follows the right-hand rule in u, then v (its control points
    # run +X along u and +Y along v), so it faces +Z.
    for source, axis in (("/World/Floor", 2), ("/World/Sheet", 2)):
        polygons = _mesh(created[source]).polygons
        inward = [i for i, p in enumerate(polygons) if p.normal[axis] <= 0]
        if inward:
            wrong[source] = (len(inward), len(polygons))
    case.check("every converted shape's faces point outward in Blender", not wrong, wrong)


def _bounds(positions: Any) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    points = [Gf.Vec3d(p) for p in positions]
    low = tuple(min(p[axis] for p in points) for axis in range(3))
    high = tuple(max(p[axis] for p in points) for axis in range(3))
    return low, high


def _same_box(a: Any, b: Any) -> bool:
    return all(abs(x - y) < TOLERANCE for corner in range(2) for x, y in zip(a[corner], b[corner], strict=True))


def _inside(inner: Any, outer: Any) -> bool:
    return all(outer[0][i] - TOLERANCE <= inner[0][i] and inner[1][i] <= outer[1][i] + TOLERANCE for i in range(3))


def _covers(inner: Any, outer: Any) -> bool:
    return all(
        inner[1][i] - inner[0][i] >= COVERAGE * (outer[1][i] - outer[0][i])
        for i in range(3)
        if outer[1][i] > outer[0][i]
    )


def _rounded(point: Any) -> tuple[float, ...]:
    return tuple(round(float(c), 5) + 0.0 for c in point)


def _on_surface(prim: Any, point: Any) -> bool:
    """Whether a local point lies on the implicit shape USD defines by the prim's parameters."""
    get = lambda name: prim.GetAttribute(name).Get(TIME)  # noqa: E731 - local shorthand
    p = [float(c) for c in point]
    if prim.GetTypeName() == "Sphere":
        return abs(math.hypot(*p) - get("radius")) < TOLERANCE
    axis = AXES[get("axis")]
    along: float = p[axis]
    radial = math.hypot(*(p[i] for i in range(3) if i != axis))
    radius, half = get("radius"), get("height") / 2
    if prim.GetTypeName() == "Capsule":  # height is the cylinder's; hemispheres cap it
        return abs(math.hypot(radial, max(abs(along) - half, 0.0)) - radius) < TOLERANCE
    if prim.GetTypeName() == "Cylinder":
        side = abs(radial - radius) < TOLERANCE and abs(along) <= half + TOLERANCE
        return side or (abs(abs(along) - half) < TOLERANCE and radial <= radius + TOLERANCE)
    if prim.GetTypeName() == "Cone":  # apex at +axis, base at -axis
        side = abs(radial - radius * (half - along) / (2 * half)) < TOLERANCE and abs(along) <= half + TOLERANCE
        return side or (abs(along + half) < TOLERANCE and radial <= radius + TOLERANCE)
    raise ValueError(f"no surface for {prim.GetTypeName()}")


def _bezier_midpoint(control: list[Any], u_count: int, v_count: int) -> Any:
    """The patch at (u, v) = (0.5, 0.5): one Bezier span each way, u varying fastest in the points."""

    def weights(count: int) -> list[float]:
        degree = count - 1
        return [math.comb(degree, i) * 0.5**degree for i in range(count)]

    total = Gf.Vec3d(0, 0, 0)
    for v, wv in enumerate(weights(v_count)):
        for u, wu in enumerate(weights(u_count)):
            total += control[v * u_count + u] * (wu * wv)
    return total


def _mesh(obj: Any) -> Any:
    return obj.data
