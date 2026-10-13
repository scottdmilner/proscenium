"""Untranslated types: a placeholder and a diagnostic for each, keeping transform, visibility, purpose, and bounds."""

from __future__ import annotations

from collections import Counter
from typing import Any

from pxr import Usd, UsdGeom

from . import oracle
from .harness import Case, codes, normalized

TIME = 1.0
GPRIMS = {
    "/World/Rig/Boxed",
    "/World/Rig/Spline",
    "/World/Rig/Unboxed",
    "/World/Rig/Dots",
    "/World/Rig/Tangents",
    "/World/Rig/Hidden",
    "/World/Rig/Guide",
    "/World/Parent",
    "/World/Fog",
    "/World/KitA/Wire",
    "/World/KitB/Wire",
}
POINT_INSTANCERS = {"/World/Scatter", "/World/KitA/Studs", "/World/KitB/Studs"}
PLACEHOLDERS = GPRIMS | POINT_INSTANCERS
# Native instance roots of each instanced placeholder, outermost first, from how the scene is built.
CONTEXTS = {s: (s.rsplit("/", 1)[0],) for s in PLACEHOLDERS if s.startswith(("/World/KitA/", "/World/KitB/"))}


def run(case: Case) -> None:
    stage = case.open("untranslated.usda")
    plan = case.native.build_plan(case.native.Bridge(stage).capture(TIME))
    by_source = {o["source"]: o for o in plan.objects}
    unsupported = {s for s in oracle.drawn_gprims(stage) if not stage.GetPrimAtPath(s).IsA(UsdGeom.Mesh)}  # ty: ignore[no-matching-overload]
    case.check("the scene's unsupported gprims are the ones the case lists", unsupported == GPRIMS, unsupported)
    instancers = _point_instancers(stage)
    case.check("the scene's point instancers are the ones the case lists", instancers == POINT_INSTANCERS, instancers)

    counts = Counter(o["source"] for o in plan.objects)
    repeated = {s: n for s, n in counts.items() if n > 1}
    case.check("every source has one object", not repeated, repeated)
    placeholders = {s for s, o in by_source.items() if o["mesh"] is None and o["placeholder_type"] is not None}
    case.check(
        "every unsupported gprim and point instancer becomes one placeholder",
        placeholders == PLACEHOLDERS,
        placeholders,
    )
    prototype_objects = sorted(s for s in counts if any(s.startswith(p + "/") for p in POINT_INSTANCERS))
    case.check("a point instancer's prototype prims get no objects", not prototype_objects, prototype_objects)
    undiagnosed = [s for s in PLACEHOLDERS if "untranslated-type" not in codes(plan, s)]
    case.check("every placeholder has an untranslated-type diagnostic on its USD path", not undiagnosed, undiagnosed)
    case.findings["placeholder types"] = {s: by_source[s]["placeholder_type"] for s in sorted(PLACEHOLDERS)}

    wrong: Any = {
        s: by_source[s]["instance_context"]
        for s in PLACEHOLDERS
        if tuple(by_source[s]["instance_context"]) != CONTEXTS.get(s, ())
    }
    case.check("each copy of an instanced placeholder has its native instance context", not wrong, wrong)
    wrong = [s for s in PLACEHOLDERS if not oracle.close(by_source[s]["matrix"], oracle.world(stage, s, TIME))]
    case.check("placeholders keep their world transforms", not wrong, wrong)
    wrong = {
        s: by_source[s]["visible"] for s in PLACEHOLDERS if by_source[s]["visible"] != oracle.visible(stage, s, TIME)
    }
    case.check("placeholders keep their effective visibility", not wrong, wrong)
    wrong = {s: by_source[s]["purpose"] for s in PLACEHOLDERS if by_source[s]["purpose"] != oracle.purpose(stage, s)}
    case.check("placeholders keep their purpose", not wrong, wrong)

    # Usable bounds: an authored extent, else USD's computed one for curves and points (oracle.placeholder_bounds).
    expected_bounds = {}
    for source in PLACEHOLDERS:
        bounds = oracle.placeholder_bounds(stage, source, TIME)
        expected_bounds[source] = None if bounds is None else normalized(bounds)
    planned_bounds = {s: normalized(by_source[s]["bounds"]) for s in PLACEHOLDERS}
    case.check(
        "usable bounds (authored, or computed for curves and points) give a bounding box; none give an empty marker",
        planned_bounds == expected_bounds,
        (planned_bounds, expected_bounds),
    )
    messages = {d["source"]: d["message"] for d in plan.diagnostics if d["code"] == "untranslated-type"}
    case.check(
        "the diagnostic says which kind of placeholder was made",
        all(("bounding-box" in messages.get(s, "")) == (expected_bounds[s] is not None) for s in PLACEHOLDERS),
        messages,
    )
    case.check(
        "a supported mesh under an unsupported ancestor is still built",
        by_source.get("/World/Parent/Child", {}).get("mesh") is not None,
    )

    created = case.apply_plan(plan)
    wrong = {}
    for source in PLACEHOLDERS:
        obj: Any = created[source]
        bounds = expected_bounds[source]
        if bounds is None:
            if obj.type != "EMPTY":
                wrong[source] = obj.type
        else:
            box = obj.bound_box
            low = tuple(min(corner[i] for corner in box) for i in range(3))
            high = tuple(max(corner[i] for corner in box) for i in range(3))
            if obj.type != "MESH" or obj.display_type != "BOUNDS" or not _close(low + high, bounds[0] + bounds[1]):
                wrong[source] = (obj.type, obj.display_type, low, high)
    case.check("Blender gets a bounds-drawn box for an extent and an empty marker otherwise", not wrong, wrong)


def _point_instancers(stage: Usd.Stage) -> set[str]:
    """Every point instancer USD composes, through instance proxies."""
    predicate = Usd.TraverseInstanceProxies(Usd.PrimDefaultPredicate)
    return {
        str(prim.GetPath())
        for prim in Usd.PrimRange(stage.GetPseudoRoot(), predicate)
        if prim.IsA(UsdGeom.PointInstancer)  # ty: ignore[no-matching-overload] - IsA also takes a schema class
    }


def _close(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return all(abs(x - y) < 1e-5 for x, y in zip(a, b, strict=True))
