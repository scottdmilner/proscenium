"""Time-code changes, edits, an unchanged refresh, and incremental captures, against USD and full captures."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from pxr import Gf, Usd, UsdGeom, UsdShade

from . import oracle
from .harness import Case, normalized

if TYPE_CHECKING:
    from collections.abc import Callable

# spec/support/visibility.md, as in the purposes case: each destination's prim purposes, and the bridge's
# default material purpose for it.
DESTINATIONS = {"viewport": ({"default", "proxy", "guide"}, "preview"), "render": ({"default", "render"}, "full")}
# USD types this scene's prims have that the prototype translates to meshes; any other gprim is a placeholder.
TRANSLATED = {"Mesh", "Cube"}
CUBE_FACES = 6
IDENTITY = normalized(Gf.Matrix4d(1.0))


def run(case: Case) -> None:
    stage = case.open("edits.usda")
    # Two bridges over one stage see the same notices: one always captures in full, the other incrementally.
    full = case.native.Bridge(stage)
    incremental = case.native.Bridge(stage)
    prim = stage.GetPrimAtPath
    paint = UsdShade.Shader(prim("/World/Looks/Paint/Surface")).GetInput("diffuseColor")

    def edit_topology() -> None:
        passenger = UsdGeom.Mesh(prim("/World/Mover/Passenger"))
        passenger.GetPointsAttr().Set([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
        passenger.GetFaceVertexCountsAttr().Set([4])
        passenger.GetFaceVertexIndicesAttr().Set([0, 1, 2, 3])

    def add_and_remove() -> None:
        UsdGeom.Cube.Define(stage, "/World/Late").GetSizeAttr().Set(0.5)
        stage.RemovePrim("/World/Blinker")

    def double_sided() -> None:
        prim("/World/Box").GetAttribute("doubleSided").Set(True)
        UsdGeom.Mesh(prim("/World/Mover/Passenger")).CreateDoubleSidedAttr().Set(True)

    def strengthen() -> None:
        rel = UsdShade.MaterialBindingAPI(prim("/World/Holder")).GetDirectBindingRel()
        UsdShade.MaterialBindingAPI.SetMaterialBindingStrength(rel, UsdShade.Tokens.strongerThanDescendants)

    def edit_kit() -> None:
        UsdGeom.Mesh(prim("/Kit/Cup")).GetPointsAttr().Set([(0, 0, 0), (2, 0, 0), (0, 2, 0)])
        UsdGeom.Xformable(prim("/Kit/Handle")).AddTranslateOp().Set(Gf.Vec3d(0, 0, 2))

    nothing: Callable[[], None] = lambda: None  # noqa: E731
    shelves = ["/World/Shelf1/Cup", "/World/Shelf2/Cup", "/World/Shelf1/Handle", "/World/Shelf2/Handle"]
    # (label, time, edit, the drawn prims whose USD values the step must change; None: no such claim).
    steps: list[tuple[str, float, Callable[[], object], set[str] | None]] = [
        ("first capture at 1", 1.0, nothing, None),
        (
            "time 2 (interpolated, Blinker and Comb hidden)",
            2.0,
            nothing,
            {"/World/Mover/Passenger", "/World/Wave", "/World/Blinker", "/World/Comb"},
        ),
        ("time 2.5", 2.5, nothing, {"/World/Mover/Passenger", "/World/Wave", "/World/Comb"}),
        ("time 3", 3.0, nothing, {"/World/Mover/Passenger", "/World/Wave", "/World/Blinker", "/World/Comb"}),
        ("unchanged refresh at 3", 3.0, nothing, set()),
        ("material parameter edit", 3.0, lambda: paint.Set(Gf.Vec3f(0.9, 0.1, 0.1)), None),
        ("cube size edit", 3.0, lambda: UsdGeom.Cube(prim("/World/Box")).GetSizeAttr().Set(3.0), {"/World/Box"}),
        ("topology edit", 3.0, edit_topology, {"/World/Mover/Passenger"}),
        ("prim added and removed", 3.0, add_and_remove, None),
        # Edits on the subset alone that change its mesh's family verdict (USD rejects a point subset in a face
        # family), which a long-lived bridge must re-read on the mesh.
        (
            "subset elementType edit (USD rejects the family)",
            3.0,
            lambda: UsdGeom.Subset(prim("/World/Patch/Strip")).GetElementTypeAttr().Set(UsdGeom.Tokens.point),
            {"/World/Patch"},
        ),
        (
            "subset elementType restored",
            3.0,
            lambda: UsdGeom.Subset(prim("/World/Patch/Strip")).GetElementTypeAttr().Set(UsdGeom.Tokens.face),
            {"/World/Patch"},
        ),
        (
            "subset familyName edit (out of materialBind)",
            3.0,
            lambda: UsdGeom.Subset(prim("/World/Patch/Strip")).GetFamilyNameAttr().Set("decor"),
            {"/World/Patch"},
        ),
        (
            "guideVisibility edit on the prim",
            3.0,
            lambda: prim("/World/Guides/Aid").GetAttribute("guideVisibility").Set("visible"),
            {"/World/Guides/Aid"},
        ),
        (
            "guideVisibility edit on an ancestor",
            3.0,
            lambda: prim("/World/Guides").GetAttribute("guideVisibility").Set("visible"),
            {"/World/Guides/Aid2"},
        ),
        ("doubleSided edits on a cube and a mesh", 3.0, double_sided, {"/World/Box", "/World/Mover/Passenger"}),
        (
            "binding retarget",
            3.0,
            lambda: (
                UsdShade.MaterialBindingAPI(prim("/World/Mover/Passenger"))
                .GetDirectBindingRel()
                .SetTargets(["/World/Looks/Ink"])
            ),
            {"/World/Mover/Passenger"},
        ),
        ("binding strength change", 3.0, strengthen, {"/World/Holder/Held"}),
        (
            "unimaged prim: translate edit",
            3.0,
            lambda: UsdGeom.Xformable(prim("/World/Brush")).AddTranslateOp().Set(Gf.Vec3d(0, 16, 0)),
            {"/World/Brush"},
        ),
        (
            "unimaged prim: visibility edit",
            3.0,
            lambda: UsdGeom.Imageable(prim("/World/Brush")).GetVisibilityAttr().Set("invisible"),
            {"/World/Brush"},
        ),
        (
            "unimaged prim: purpose edit",
            3.0,
            lambda: UsdGeom.Imageable(prim("/World/Brush")).GetPurposeAttr().Set("guide"),
            {"/World/Brush"},
        ),
        ("instance prototype content edit", 3.0, edit_kit, set(shelves)),
        ("back to time 1", 1.0, nothing, {"/World/Mover/Passenger", "/World/Wave", "/World/Comb"}),
        ("unchanged refresh at 1", 1.0, nothing, set()),
    ]

    log = []
    mismatched_values: dict[str, Any] = {}
    mismatched_incremental: dict[str, Any] = {}
    mismatched_fresh: dict[str, Any] = {}
    ineffective_edits: dict[str, Any] = {}
    dirtied_unchanged: dict[str, list[str]] = {}
    previous_records: dict[str, Any] = {}
    previous_expected: dict[str, Any] = {}
    previous_plan: Any = None
    plans: dict[str, Any] = {}
    unchanged: dict[str, Any] = {}
    for label, time, action, targets in steps:
        action()
        snapshot = full.capture(time)
        shared = incremental.capture(time, incremental=previous_plan is not None)
        plan = case.native.build_plan(snapshot)
        plans[label] = plan

        records = {path: _record(snapshot.prim(path)) for path in snapshot.paths()}
        shared_records = {path: _record(shared.prim(path)) for path in shared.paths()}
        if records != shared_records or _plan(plan) != _plan(case.native.build_plan(shared)):
            mismatched_incremental[label] = (
                sorted(p for p in set(records) | set(shared_records) if records.get(p) != shared_records.get(p))
                or "plans differ"
            )

        fresh = case.native.Bridge(stage)
        fresh_plan = case.native.build_plan(fresh.capture(time))
        fresh.release()
        if _plan(plan) != _plan(fresh_plan):
            mismatched_fresh[label] = _plan_difference(_plan(plan), _plan(fresh_plan))

        expected = _expected(stage, time)
        wrong = _against_usd(stage, plan, expected, time)
        if wrong:
            mismatched_values[label] = wrong
        if targets is not None:
            changed = {s for s in set(expected) | set(previous_expected) if expected.get(s) != previous_expected.get(s)}
            if changed != targets:
                ineffective_edits[label] = {"expected to change": sorted(targets), "changed": sorted(changed)}
        dirtied = {path for kind, path in snapshot.events if kind == "dirtied"}
        # Dirtied prims whose captured record didn't change: the notices over-report.
        over = sorted(p for p in dirtied if p in previous_records and records.get(p) == previous_records[p])
        if over:
            dirtied_unchanged[label] = over
        log.append(
            {
                "step": label,
                "notices": len(snapshot.events),
                "dirtied prims": len(dirtied),
                "dirtied but unchanged": len(over),
                "prims": len(records),
                "copied by the incremental capture": shared.copied,
            }
        )
        if label.startswith("unchanged"):
            unchanged[label] = (snapshot.events, shared.copied, _plan(plan) == _plan(previous_plan))
        previous_records, previous_expected, previous_plan = records, expected, plan

    case.findings["steps"] = log
    case.findings["dirtied but unchanged, by step"] = dirtied_unchanged
    case.check(
        "every time step and edit changes USD's values for exactly the prims the scene varies there",
        not ineffective_edits,
        ineffective_edits,
    )
    case.check("plans match USD at every time and after every edit", not mismatched_values, mismatched_values)
    case.check(
        "an unchanged refresh delivers no notices, copies no prims incrementally, and plans identically",
        all(events == [] and copied == 0 and same for events, copied, same in unchanged.values()),
        unchanged,
    )
    case.check(
        "incremental captures match full captures, record by record, after every step",
        not mismatched_incremental,
        mismatched_incremental,
    )
    case.check(
        "a long-lived bridge plans what a new bridge plans, after every step", not mismatched_fresh, mismatched_fresh
    )

    def paint_color(plan: Any) -> Any:
        (material,) = [m for m in plan.materials if "/World/Looks/Paint" in m["sources"]]
        return normalized(material["parameters"]["diffuseColor"])

    case.check(
        "a material parameter edit reaches the next plan, and not the plans before it",
        paint_color(plans["material parameter edit"]) == normalized(Gf.Vec3f(0.9, 0.1, 0.1))
        and paint_color(plans["time 3"]) == normalized(Gf.Vec3f(0.2, 0.4, 0.6)),
    )
    after_add = {o["source"] for o in plans["prim added and removed"].objects}
    case.check(
        "added and removed prims appear in and disappear from the next plan",
        "/World/Late" in after_add and "/World/Blinker" not in after_add,
        sorted(after_add),
    )
    full.release()
    incremental.release()


def _record(record: Any) -> Any:
    """A snapshot record for comparison. Hydra fills an instancer's `matrix` with identity in one graph and
    leaves it out in another; planning treats both as identity, so they compare equal here."""
    result = normalized(record)
    if result is not None and result.get("matrix") is None:
        result["matrix"] = IDENTITY
    return result


def _plan(plan: Any) -> Any:
    if plan is None:
        return None
    return normalized(
        {"meshes": plan.meshes, "materials": plan.materials, "objects": plan.objects, "diagnostics": plan.diagnostics}
    )


def _plan_difference(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """The first differing entries of each plan list, for the failure message."""
    difference: dict[str, Any] = {}
    for key in a:
        if a[key] != b[key]:
            pairs = [(x, y) for x, y in zip(a[key], b[key], strict=False) if x != y]
            difference[key] = {"lengths": (len(a[key]), len(b[key])), "first": pairs[:2]}
    return difference


def _expected(stage: Usd.Stage, time: float) -> dict[str, dict[str, Any]]:
    """USD's values at `time` for every drawn gprim: what each planned object must show."""
    expected = {}
    for source, roots in oracle.drawn_gprims(stage).items():
        prim = stage.GetPrimAtPath(source)
        purpose = str(UsdGeom.Imageable(prim).ComputePurpose())
        visible = oracle.visible(stage, source, time)
        entry: dict[str, Any] = {
            "roots": roots,
            "matrix": normalized(oracle.world(stage, source, time)),
            "visible": visible,
            "purpose": oracle.purpose(stage, source),
            "destinations": {d for d, (purposes, _) in DESTINATIONS.items() if visible and purpose in purposes},
            "displayColor": normalized(oracle.display_color(stage, source, time)),
        }
        type_name = str(prim.GetTypeName())
        if type_name in TRANSLATED:
            entry["double_sided"] = bool(UsdGeom.Gprim(prim).GetDoubleSidedAttr().Get(time))
            entry["materials"] = {d: _face_materials(stage, source, time, mp) for d, (_, mp) in DESTINATIONS.items()}
            if type_name == "Mesh":
                entry["points"] = normalized(UsdGeom.Mesh(prim).GetPointsAttr().Get(time))
            else:
                extent = UsdGeom.Boundable.ComputeExtentFromPlugins(UsdGeom.Boundable(prim), time)
                entry["extent"] = normalized(tuple(extent))
        else:
            bounds = oracle.placeholder_bounds(stage, source, time)
            entry["bounds"] = None if bounds is None else normalized(bounds)
        expected[source] = entry
    return expected


def _face_materials(stage: Usd.Stage, source: str, time: float, material_purpose: str) -> list[str | None]:
    prim = stage.GetPrimAtPath(source)
    if prim.IsA(UsdGeom.Mesh):  # ty: ignore[no-matching-overload] - IsA also takes a schema class
        return oracle.face_materials(stage, source, time, material_purpose)
    # A cube has six faces and no subsets.
    return [oracle.bound_material(prim, material_purpose)] * CUBE_FACES


def _against_usd(stage: Usd.Stage, plan: Any, expected: dict[str, Any], time: float) -> dict[str, Any]:
    """Every planned object against USD, and every plan material's parameters against its USD shader."""
    wrong: dict[str, Any] = {}
    objects: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in plan.objects:
        objects[obj["source"]].append(obj)
    if set(objects) != set(expected):
        wrong["sources"] = (sorted(objects), sorted(expected))
        return wrong
    for source, usd in expected.items():
        mine = objects[source]
        materials = usd.get("materials")
        split = len(usd["destinations"]) == 2 and materials is not None and materials["viewport"] != materials["render"]
        if len(mine) != (2 if split else 1):
            wrong[f"{source} objects"] = len(mine)
        for destination in DESTINATIONS:
            shown = [o for o in mine if o[destination]]
            if len(shown) != (destination in usd["destinations"]):
                wrong[f"{source} {destination}"] = len(shown)
            for obj in shown:
                if materials is not None and obj["mesh"] is not None:
                    planned = oracle.plan_face_materials(plan, obj)
                    if not oracle.materials_match(materials[destination], planned, exact=not usd["roots"]):
                        wrong[f"{source} {destination} materials"] = (materials[destination], planned)
        for obj in mine:
            wrong.update(_object_against_usd(plan, source, obj, usd))
    for material in plan.materials:
        for source in material["sources"]:
            shader = UsdShade.Material(stage.GetPrimAtPath(source)).ComputeSurfaceSource()[0]
            usd_color = shader.GetInput("diffuseColor").Get(time) if shader else None
            if normalized(material["parameters"].get("diffuseColor")) != normalized(usd_color):
                wrong[f"{source} diffuseColor"] = (material["parameters"].get("diffuseColor"), usd_color)
    return wrong


def _object_against_usd(plan: Any, source: str, obj: dict[str, Any], usd: dict[str, Any]) -> dict[str, Any]:
    wrong: dict[str, Any] = {}
    if not oracle.close(obj["matrix"], usd["matrix"]):
        wrong[f"{source} matrix"] = obj["matrix"]
    for key in ("visible", "purpose"):
        if obj[key] != usd[key]:
            wrong[f"{source} {key}"] = obj[key]
    if normalized(obj["primvars"].get("displayColor")) != usd["displayColor"]:
        wrong[f"{source} displayColor"] = obj["primvars"].get("displayColor")
    if tuple(obj["instance_context"]) != usd["roots"]:
        wrong[f"{source} instance context"] = obj["instance_context"]
    if "bounds" in usd:  # a placeholder
        if obj["mesh"] is not None or obj["placeholder_type"] is None:
            wrong[f"{source} placeholder"] = (obj["mesh"], obj["placeholder_type"])
        elif normalized(obj["bounds"]) != usd["bounds"]:
            wrong[f"{source} bounds"] = (obj["bounds"], usd["bounds"])
        return wrong
    if obj["mesh"] is None:
        wrong[f"{source} mesh"] = None
        return wrong
    mesh = plan.meshes[obj["mesh"]]
    if mesh["double_sided"] != usd["double_sided"]:
        wrong[f"{source} doubleSided"] = mesh["double_sided"]
    positions = normalized(mesh["positions"])
    if "points" in usd and not _points_close(positions, usd["points"]):
        wrong[f"{source} points"] = (positions, usd["points"])
    if "extent" in usd:
        box = (
            tuple(min(p[i] for p in positions) for i in range(3)),
            tuple(max(p[i] for p in positions) for i in range(3)),
        )
        if not _points_close(box, usd["extent"]):
            wrong[f"{source} extent"] = (box, usd["extent"])
    return wrong


def _points_close(a: Any, b: Any) -> bool:
    return len(a) == len(b) and all(
        abs(x - y) < 1e-5 for p, q in zip(a, b, strict=True) for x, y in zip(p, q, strict=True)
    )
