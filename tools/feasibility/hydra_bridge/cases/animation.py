"""Time-varying values captured frame by frame: what a time change dirties, and the plan at each time, against USD.

Each capture evaluates one time code. A time change must dirty every value that varies, so an incremental
capture re-copies it, and the plan must match USD at every time. Direct USD (ValueMightBeTimeVarying on every
attribute a value depends on) is checked against the scene's construction first, and is the expected set of
dirties.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pxr import Usd, UsdGeom, UsdSkel

from . import oracle
from .harness import Case, normalized

START, END = 1.0, 3.0
TIMES = [1.0, 1.5, 2.0, 3.0]
# What varies over [1, 3], by prim and kind of value, from how animation.usda is built. Instance copies are
# listed by their USD (instance-proxy) paths; Hydra reports them on their instancer.
EXPECTED: dict[str, set[str]] = {
    "/World/Wave": {"points"},
    "/World/Steady": {"points"},  # two samples, equal in value: time-varying to USD
    "/World/Rig": {"transform"},
    "/World/Rig/Arm": {"transform"},
    "/World/Rig/Arm/Hand": {"transform"},
    "/World/Spin": {"transform"},
    "/World/Spin/Turned": {"transform"},
    "/World/Spin/Turned/Blade": {"transform"},
    "/World/Blinker": {"visibility"},
    "/World/Shade": {"visibility"},
    "/World/Shade/Shaded": {"visibility"},
    "/World/Shade/Hid": {"visibility"},
    "/World/Shade/Hid/Blade": {"visibility"},
    "/World/Morph": {"topology"},
    "/World/Tinted": {"primvar:displayColor", "primvar:level"},
    "/World/Remapped": {"primvar:weight"},
    "/World/Tagged": {"primvar:faceId"},
    "/World/Split/First": {"subset"},
    "/World/Split/Second": {"subset"},
    "/World/Aid": {"guideVisibility"},
    "/World/Comb": {"transform"},
    "/World/Strands": {"points"},
    "/World/Skinned/Body": {"points"},
    # Hydra draws a skeleton as a bone mesh whose points follow the joints.
    "/World/Skinned/Skel": {"points"},
}
# Hydra prims that feed skinning and aren't drawn.
SKINNING_INPUTS = {"/World/Skinned/Body/skinningPointsComputation", "/World/Skinned/Skel/Anim"}
# The one instancer's varying values: Turned's transform and Hid's visibility, both from an ancestor.
INSTANCER_VARYING = {"transform", "visibility"}
SKINNED = "/World/Skinned/Body"


def kind(locator: str) -> str:
    """The kind of value a Hydra locator names, in EXPECTED's terms."""
    parts = locator.split("/")
    if parts[0] in ("xform", "visibility", "extent"):
        return {"xform": "transform"}.get(parts[0], parts[0])
    if parts[0] == "instancerTopology" and parts[1:2] == ["mask"]:
        return "visibility"
    if parts[0] == "primvars" and len(parts) > 1:
        return {"points": "points", "hydra:instanceTransforms": "transform"}.get(parts[1], f"primvar:{parts[1]}")
    if parts[0] == "mesh" and parts[1:2] == ["topology"]:
        return "topology"
    if locator == "geomSubset/indices":
        return "subset"
    if parts[0] == "resolvedSkeleton":
        return "joints"
    if locator == "prosceniumSource/guide":
        return "guideVisibility"
    return locator


def contributing(stage: Usd.Stage, path: str) -> dict[str, list[Usd.Attribute]]:
    """Direct USD: per kind, the authored attributes a prim's value depends on, ancestors' and the skeleton
    animation's included."""
    prim = stage.GetPrimAtPath(path)
    result: dict[str, list[Usd.Attribute]] = defaultdict(list)
    ancestor = prim
    while ancestor and not ancestor.IsPseudoRoot():
        if xformable := UsdGeom.Xformable(ancestor):
            result["transform"] += [op.GetAttr() for op in xformable.GetOrderedXformOps()]
        if imageable := UsdGeom.Imageable(ancestor):
            result["visibility"].append(imageable.GetVisibilityAttr())
        ancestor = ancestor.GetParent()
    if point_based := UsdGeom.PointBased(prim):
        result["points"].append(point_based.GetPointsAttr())
    if mesh := UsdGeom.Mesh(prim):
        result["topology"] += [mesh.GetFaceVertexCountsAttr(), mesh.GetFaceVertexIndicesAttr()]
    for primvar in UsdGeom.PrimvarsAPI(prim).GetAuthoredPrimvars():
        if primvar.GetPrimvarName().startswith("skel:"):
            continue  # skinning inputs, below
        result[f"primvar:{primvar.GetPrimvarName()}"] += [primvar.GetAttr(), primvar.GetIndicesAttr()]
    if subset := UsdGeom.Subset(prim):
        result["subset"].append(subset.GetIndicesAttr())
    if prim.HasAPI(UsdGeom.VisibilityAPI):  # ty: ignore[no-matching-overload] - HasAPI also takes a schema class
        result["guideVisibility"].append(UsdGeom.VisibilityAPI(prim).GetGuideVisibilityAttr())
    skeleton = UsdSkel.Skeleton(prim) or UsdSkel.BindingAPI(prim).GetInheritedSkeleton()
    if skeleton and (prim.IsA(UsdGeom.Mesh) or prim.IsA(UsdSkel.Skeleton)):  # ty: ignore[no-matching-overload] - IsA also takes a schema class
        animation = UsdSkel.BindingAPI(skeleton.GetPrim()).GetInheritedAnimationSource()
        if animation:
            result["points"] += [
                attribute for attribute in animation.GetPrim().GetAttributes() if attribute.HasAuthoredValue()
            ]
    return {k: [a for a in v if a and a.HasAuthoredValue()] for k, v in result.items()}


def usd_varying(stage: Usd.Stage, path: str) -> set[str]:
    return {
        k for k, attributes in contributing(stage, path).items() if any(a.ValueMightBeTimeVarying() for a in attributes)
    }


def dirtied(snapshot: Any, skip: set[str]) -> dict[str, set[str]]:
    """Per Hydra prim: the kinds its dirty notices name."""
    return {
        p: {kind(locator) for locator in locators} for p, locators in snapshot.dirty_locators.items() if p not in skip
    }


def skinned_points(stage: Usd.Stage, time: float) -> list[tuple[float, ...]]:
    """UsdSkel's own skinning of Body (every transform in the scene is identity, so skeleton space is local)."""
    cache = UsdSkel.Cache()
    root = UsdSkel.Root(stage.GetPrimAtPath("/World/Skinned"))
    cache.Populate(root, Usd.PrimDefaultPredicate)
    body = stage.GetPrimAtPath(SKINNED)
    skeleton = UsdSkel.BindingAPI(body).GetInheritedSkeleton()
    transforms = cache.GetSkelQuery(skeleton).ComputeSkinningTransforms(time)
    points = UsdGeom.Mesh(body).GetPointsAttr().Get(time)
    cache.GetSkinningQuery(body).ComputeSkinnedPoints(transforms, points, time)
    return [tuple(p) for p in points]


def run(case: Case) -> None:
    stage = case.open("animation.usda")
    expected_usd = {path: usd_varying(stage, path) for path in EXPECTED}
    wrong = {p: (expected_usd[p], kinds) for p, kinds in EXPECTED.items() if expected_usd[p] != kinds}
    static = {
        p: usd_varying(stage, p) for p in oracle.drawn_gprims(stage) if p not in EXPECTED and usd_varying(stage, p)
    }
    case.check(
        "direct USD (ValueMightBeTimeVarying on each attribute a value depends on, ancestors' and the skeleton "
        "animation's included) reports exactly the values built to vary",
        not wrong and not static,
        (wrong, static),
    )
    steady = UsdGeom.Mesh(stage.GetPrimAtPath("/World/Steady")).GetPointsAttr()
    single = UsdGeom.Mesh(stage.GetPrimAtPath("/World/Single")).GetPointsAttr()
    case.check(
        "direct USD over-reports equal samples and ignores a single sample",
        steady.ValueMightBeTimeVarying()
        and steady.Get(START) == steady.Get(END)
        and not single.ValueMightBeTimeVarying(),
    )

    # Instance proxies aren't Hydra prims; their copies' values are the instancer's.
    bridge = case.native.Bridge(stage)
    instancers = [p for p in bridge.capture(START).paths() if p.endswith("/UsdNiInstancer")]
    case.check("the two Leaf instances share one instancer", len(instancers) == 1, instancers)
    hydra_expected = {p: set(k) for p, k in EXPECTED.items() if not stage.GetPrimAtPath(p).IsInstanceProxy()}
    hydra_expected[instancers[0]] = set(INSTANCER_VARYING)

    # Beside the values themselves: the filter's computed extent follows the points, and the skeleton's
    # resolved skinning transforms follow its animation.
    expected_dirties = {p: set(k) for p, k in hydra_expected.items()}
    expected_dirties["/World/Strands"].add("extent")
    expected_dirties["/World/Skinned/Skel"].add("joints")
    changes = {}
    for time in TIMES[1:]:
        changes[time] = dirtied(bridge.capture(time), SKINNING_INPUTS)
    case.findings["dirtied kinds per time change"] = {
        str(t): {p: sorted(k) for p, k in d.items()} for t, d in changes.items()
    }
    wrong = {t: (d, expected_dirties) for t, d in changes.items() if d != expected_dirties}
    case.check(
        "each time change dirties exactly the values built to vary, visibility and computed extents included",
        not wrong,
        wrong,
    )
    check_values(case, stage)


def check_values(case: Case, stage: Usd.Stage) -> None:
    """At each time, the plan from a full and from an incremental capture matches USD."""
    full = case.native.Bridge(stage)
    incremental = case.native.Bridge(stage)
    wrong: dict[str, Any] = {}
    differs = []
    bones: dict[str, Any] = {}
    for time in TIMES + [1.0]:
        plan = case.native.build_plan(full.capture(time))
        again = case.native.build_plan(incremental.capture(time, incremental=True))
        if normalized(plan.objects) != normalized(again.objects) or normalized(plan.meshes) != normalized(again.meshes):
            differs.append(time)
        for obj in plan.objects:
            source = obj["source"]
            label = f"{source} at {time}"
            prim = stage.GetPrimAtPath(source)
            if prim.IsA(UsdSkel.Skeleton):  # ty: ignore[no-matching-overload] - IsA also takes a schema class
                # UsdSkelImaging's bone mesh: Hydra content with no USD geometry to compare.
                bones[str(time)] = {"purpose": obj["purpose"], "visible": obj["visible"]}
                continue
            if not oracle.close(obj["matrix"], oracle.world(stage, source, time)):
                wrong[f"{label} matrix"] = obj["matrix"]
            if obj["visible"] != oracle.visible(stage, source, time):
                wrong[f"{label} visible"] = obj["visible"]
            if obj["mesh"] is None:
                if obj["bounds"] is not None or oracle.placeholder_bounds(stage, source, time) is not None:
                    usd = oracle.placeholder_bounds(stage, source, time)
                    if usd is None or obj["bounds"] is None or normalized(obj["bounds"]) != normalized(usd):
                        wrong[f"{label} bounds"] = (obj["bounds"], usd)
                continue
            mesh = plan.meshes[obj["mesh"]]
            usd_mesh = UsdGeom.Mesh(prim)
            points = (
                skinned_points(stage, time)
                if source == SKINNED
                else [tuple(p) for p in usd_mesh.GetPointsAttr().Get(time)]
            )
            if not oracle.all_close([tuple(p) for p in mesh["positions"]], points):
                wrong[f"{label} points"] = (list(mesh["positions"]), points)
            layout = oracle.mesh_layout(usd_mesh, time)
            if list(mesh["corner_verts"]) != layout["corner_verts"] or len(mesh["face_offsets"]) != layout["faces"]:
                wrong[f"{label} topology"] = (list(mesh["corner_verts"]), layout["corner_verts"])
            faces = oracle.face_materials(stage, source, time, "preview")
            if not oracle.materials_match(
                faces, oracle.plan_face_materials(plan, obj), exact=not obj["instance_context"]
            ):
                wrong[f"{label} materials"] = (faces, oracle.plan_face_materials(plan, obj))
            attributes = {a["name"]: a for a in mesh["attributes"]}
            for name in ("weight", "faceId"):
                primvar = UsdGeom.PrimvarsAPI(prim).GetPrimvar(name)
                if not primvar:
                    continue
                usd = [oracle.components(v) for v in primvar.ComputeFlattened(time)]
                got = [oracle.components(v) for v in attributes[name]["data"]] if name in attributes else None
                if got is None or not oracle.all_close(got, usd):
                    wrong[f"{label} {name}"] = (got, usd)
            for name in ("displayColor", "level"):
                usd = oracle.inherited_primvar(stage, source, name, time)
                if usd is None:
                    continue
                value = obj["properties"].get(name)
                held = usd[0] if name == "displayColor" else usd
                if value is None or not oracle.all_close([oracle.components(value)], [oracle.components(held)]):
                    wrong[f"{label} {name}"] = (value, held)
    case.check(
        "at times 1, 1.5, 2 and 3, and back at 1, the plan matches USD: transforms, visibility (the guide's "
        "animated guideVisibility included), points (skinned by UsdSkel for Body), topology, per-face "
        "materials from animated subsets, primvars with animated values or indices, constant primvars as "
        "properties, and computed placeholder bounds",
        not wrong,
        wrong,
    )
    case.check("incremental captures plan identically to full ones at each time", not differs, differs)
    case.findings["the skeleton's bone mesh, by time"] = bones
    body = next(o for o in case.native.build_plan(full.capture(1.0)).objects if o["source"] == SKINNED)
    case.findings["UsdSkel primvars planned on Body, though skinning consumed them"] = {
        "attributes": [a["name"] for a in case.native.build_plan(full.capture(1.0)).meshes[body["mesh"]]["attributes"]],
        "properties": sorted(body["properties"]),
    }
