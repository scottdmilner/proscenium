"""Mesh with GeomSubsets and indexed primvars: indices kept, subsets mapped to material slots, uncovered faces.

Also the corner order of a left-handed mesh, domain conversions, reserved names, overlapping subsets and
subsets of points (see subsets.usda).
"""

from __future__ import annotations

from typing import Any

from pxr import Gf, UsdGeom, UsdShade

from . import oracle
from .harness import Case, codes, normalized

TIME = 1.0
MESHES = ("/World/Strip", "/World/Loose", "/World/Mixed", "/World/Overlap")
# Meshes whose faces UsdShade's materialBind assignment defines; Overlap's subsets overlap, which UsdShade leaves
# undefined, so the core's rule (the first subset by name) is checked on its own.
WELL_FORMED = ("/World/Strip", "/World/Loose", "/World/Mixed")
PRIMVAR_MESHES = ("/World/Strip", "/World/Mixed")
# Blender's domain for each USD interpolation; texture coordinates always go on corners, as UV maps.
DOMAINS = {"vertex": "POINT", "varying": "POINT", "uniform": "FACE", "faceVarying": "CORNER"}
# Names Blender gives a meaning of its own; the planner must not transfer them.
RESERVED = {"sharp_face"}


def run(case: Case) -> None:
    stage = case.open("subsets.usda")
    snapshot = case.native.Bridge(stage).capture(TIME)
    plan = case.native.build_plan(snapshot)
    by_source = {o["source"]: o for o in plan.objects}

    wrong = []
    for source in PRIMVAR_MESHES:
        captured = snapshot.prim(source)["primvars"]
        for primvar in UsdGeom.PrimvarsAPI(stage.GetPrimAtPath(source)).GetAuthoredPrimvars():
            name = primvar.GetPrimvarName()
            record = captured.get(name)
            expected_indices = normalized(primvar.GetIndices(TIME)) if primvar.IsIndexed() else None
            if (
                record is None
                or normalized(record["values"]) != normalized(primvar.Get(TIME))
                or (None if record["indices"] is None else normalized(record["indices"])) != expected_indices
            ):
                wrong.append(f"{source}.{name}")
    case.check("indexed primvars keep their indices and unflattened values; others have no indices", not wrong, wrong)

    strip = UsdGeom.Mesh(stage.GetPrimAtPath("/World/Strip"))
    families = {}
    for subset in UsdGeom.Subset.GetAllGeomSubsets(strip):
        record = snapshot.prim(str(subset.GetPath()))["subset"]
        families[subset.GetPrim().GetName()] = (record["family_name"], subset.GetFamilyNameAttr().Get())
    case.check(
        "subset family names reach the snapshot through the source-info filter",
        len(families) == 5 and all(captured_family == usd for captured_family, usd in families.values()),
        families,
    )
    unfamilied = "/World/Strip/Unfamilied"
    authored = stage.GetPrimAtPath(unfamilied).GetAttribute("familyName").HasAuthoredValue()
    case.check(
        "a subset with no familyName authored has USD's fallback, the empty family, in the snapshot",
        not authored and families["Unfamilied"] == ("", ""),
        (authored, families["Unfamilied"]),
    )
    # Why the family matters: Hydra binds a subset of any family, this one included.
    purple = "/World/Looks/Purple"
    hydra_bindings = snapshot.prim(unfamilied)["material_bindings"]
    case.known_gap(
        "Hydra binds a subset with no family, which UsdShade ignores (the planner uses only materialBind subsets)",
        purple in hydra_bindings.values() and oracle.bound_material(stage.GetPrimAtPath(unfamilied)) == purple,
        hydra_bindings,
    )

    expected_faces = {source: oracle.face_materials(stage, source, TIME) for source in WELL_FORMED}
    expected_faces["/World/Overlap"] = _first_by_name(stage, "/World/Overlap")
    wrong = {}
    for source, expected in expected_faces.items():
        planned = oracle.plan_face_materials(plan, by_source[source])
        if not oracle.materials_match(expected, planned, exact=True):
            wrong[source] = (expected, planned)
    case.check(
        "each face gets UsdShade's materialBind assignment, and faces in no subset take the mesh's binding or none",
        not wrong,
        wrong,
    )
    outside = {"/World/Looks/Yellow", purple}  # bound by Tagged (componentTag) and Unfamilied (no family)
    strip_faces = oracle.plan_face_materials(plan, by_source["/World/Strip"])
    case.check(
        "a subset outside the materialBind family, or in none, assigns no material: face 3 keeps the mesh's Blue",
        all(sources is None or not sources & outside for sources in strip_faces)
        and strip_faces[3] == {"/World/Looks/Blue"},
        strip_faces,
    )

    overlap = UsdGeom.Imageable(stage.GetPrimAtPath("/World/Overlap"))
    valid_family, _ = UsdGeom.Subset.ValidateFamily(overlap, UsdGeom.Tokens.face, "materialBind")
    case.check(
        "overlapping materialBind subsets: USD reports the family invalid, the plan warns, and face 0 takes A_Red",
        not valid_family
        and "overlapping-subsets" in codes(plan, "/World/Overlap")
        and expected_faces["/World/Overlap"][0] == "/World/Looks/Red",
        (valid_family, codes(plan, "/World/Overlap"), expected_faces["/World/Overlap"]),
    )
    # Points is in the materialBind family but lists points; slot 0, then one slot per face subset.
    overlap_mesh = plan.meshes[by_source["/World/Overlap"]["mesh"]]
    case.check(
        "a materialBind subset of points is ignored with an unsupported-subset warning",
        "unsupported-subset" in codes(plan, "/World/Overlap") and overlap_mesh["slot_count"] == 4,
        (codes(plan, "/World/Overlap"), overlap_mesh["slot_count"]),
    )

    created = case.apply_plan(plan)
    expected_loose = oracle.face_materials(stage, "/World/Loose", TIME)
    case.check(
        "with nothing bound on the mesh, its faces outside a subset and in an unbound subset have no material",
        expected_loose == [None, "/World/Looks/Red", None],
        expected_loose,
    )
    wrong = {}
    for source, expected in expected_faces.items():
        obj: Any = created[source]
        faces = []
        for polygon in obj.data.polygons:
            material = obj.material_slots[polygon.material_index].material
            faces.append(None if material is None else set(material["proscenium_sources"]))
        if not oracle.materials_match(expected, faces, exact=True):
            wrong[source] = (expected, faces)
    case.check("each face's material in Blender, through its object's slots, is UsdShade's", not wrong, wrong)
    invalid = [s for s in MESHES if _mesh(created[s]).validate()]
    case.check("Blender accepts every mesh unchanged", not invalid, invalid)

    # USD's own verdict on each mesh's materialBind family (UsdGeomSubset.ValidateFamily) reaches the plan.
    verdicts, reported = {}, {}
    for source in ("/World/Strip", "/World/Loose", "/World/Overlap"):
        valid, reason = UsdGeom.Subset.ValidateFamily(
            UsdGeom.Imageable(stage.GetPrimAtPath(source)), "face", "materialBind"
        )
        verdicts[source] = None if valid else reason
        messages = [
            d["message"] for d in plan.diagnostics if d["source"] == source and d["code"] == "invalid-subset-family"
        ]
        reported[source] = messages[0].split(": ", 1)[1] if messages else None
    case.check(
        "a materialBind family USD rejects is diagnosed with USD's reason, and one it accepts is not",
        reported == verdicts and verdicts["/World/Overlap"] is not None,
        (reported, verdicts),
    )

    # USD's scheme, fallback included; the prototype draws the cage, so only a subdividing scheme is warned.
    schemes = {
        s: UsdGeom.Mesh(stage.GetPrimAtPath(s)).GetSubdivisionSchemeAttr().Get()
        for s in ("/World/Smooth", "/World/Hard", "/World/Strip")
    }
    warned = {s: "subdivision-not-applied" in codes(plan, s) for s in schemes}
    case.check(
        "a subdividing scheme (catmullClark by USD's fallback) is diagnosed as not applied; bilinear and none are not",
        schemes == {"/World/Smooth": "catmullClark", "/World/Hard": "bilinear", "/World/Strip": "none"}
        and warned == {"/World/Smooth": True, "/World/Hard": False, "/World/Strip": False},
        (schemes, warned),
    )

    wrong = {}
    for source in PRIMVAR_MESHES:
        mesh: Any = created[source].data
        usd = UsdGeom.Mesh(stage.GetPrimAtPath(source))
        layout = oracle.mesh_layout(usd, TIME)
        corner_verts = [loop.vertex_index for loop in mesh.loops]
        if corner_verts != layout["corner_verts"]:
            wrong[f"{source} corners"] = (corner_verts, layout["corner_verts"])
        for primvar in UsdGeom.PrimvarsAPI(usd).GetAuthoredPrimvars():
            name = primvar.GetPrimvarName()
            if primvar.GetInterpolation() == UsdGeom.Tokens.constant or name in RESERVED:
                continue
            texcoord = primvar.GetTypeName().role == "TextureCoordinate"
            flattened = [oracle.components(v) for v in primvar.ComputeFlattened(TIME)]
            if primvar.GetTypeName().role == "Color":
                flattened = [(*v, 1.0) for v in flattened]
            expected = oracle.on_domain(flattened, primvar.GetInterpolation(), texcoord, layout)
            if texcoord:
                layer = mesh.uv_layers.get(name)
                values = None if layer is None else [oracle.components(d.uv) for d in layer.data]
            else:
                attribute = mesh.attributes.get(name)
                domain = DOMAINS[primvar.GetInterpolation()]
                values = (
                    None
                    if attribute is None or attribute.domain != domain
                    else [oracle.element_value(d) for d in attribute.data]
                )
            if values is None or not oracle.all_close(values, expected):
                wrong[f"{source}.{name}"] = (values, expected)
    case.check(
        "corners and attributes match USD's flattened primvars on Blender's domains, left-handed faces reversed",
        not wrong,
        wrong,
    )

    # USD's right-handed normal of corners 0, 1, 2, negated for a left-handed mesh, is Blender's face normal.
    wrong = {}
    for source in PRIMVAR_MESHES:
        usd = UsdGeom.Mesh(stage.GetPrimAtPath(source))
        layout = oracle.mesh_layout(usd, TIME)
        points = [Gf.Vec3d(p) for p in usd.GetPointsAttr().Get(TIME)]
        sign = -1.0 if usd.GetOrientationAttr().Get() == UsdGeom.Tokens.leftHanded else 1.0
        for face, polygon in enumerate(_mesh(created[source]).polygons):
            a, b, c = (points[i] for i in layout["usd_faces"][face][:3])
            expected = (Gf.Cross(b - a, c - a) * sign).GetNormalized()
            if not oracle.all_close([oracle.components(polygon.normal)], [oracle.components(expected)], 1e-5):
                wrong[f"{source} face {face}"] = (oracle.components(polygon.normal), oracle.components(expected))
    case.check("each face's Blender normal follows USD's orientation", not wrong, wrong)

    mixed: Any = created["/World/Mixed"]
    expected_color = oracle.inherited_primvar(stage, "/World/Mixed", "displayColor", TIME)
    planned_color = by_source["/World/Mixed"]["primvars"].get("displayColor")
    case.check(
        "an indexed constant displayColor reaches the object flattened, as ComputeFlattened gives it",
        expected_color is not None
        and planned_color is not None
        and normalized(planned_color) == normalized(expected_color)
        and oracle.all_close([oracle.components(mixed.color)], [(*oracle.components(expected_color[0]), 1.0)]),
        (planned_color, expected_color, tuple(mixed.color)),
    )
    reserved = [d for d in plan.diagnostics if d["code"] == "untransferred-primvar" and "'sharp_face'" in d["message"]]
    case.check(
        "a primvar named sharp_face is not transferred, with a diagnostic, and every face stays smooth-shaded",
        len(reserved) == 1
        and reserved[0]["source"] == "/World/Mixed"
        and "sharp_face" not in mixed.data.attributes
        and all(p.use_smooth for p in mixed.data.polygons),
        (reserved, [p.use_smooth for p in mixed.data.polygons]),
    )
    case.findings["material slots"] = {source: by_source[source]["material_slots"] for source in MESHES}


def _first_by_name(stage: Any, source: str) -> list[str | None]:
    """The core's rule for overlapping materialBind subsets: each face takes the first face subset by name."""
    mesh = UsdGeom.Mesh(stage.GetPrimAtPath(source))
    faces: list[str | None] = [oracle.bound_material(mesh.GetPrim())] * len(mesh.GetFaceVertexCountsAttr().Get(TIME))
    assigned = [False] * len(faces)
    subsets = UsdShade.MaterialBindingAPI(mesh.GetPrim()).GetMaterialBindSubsets()
    for subset in sorted(subsets, key=lambda s: s.GetPrim().GetName()):
        if subset.GetElementTypeAttr().Get() != UsdGeom.Tokens.face:
            continue
        for face in subset.GetIndicesAttr().Get(TIME):
            if not assigned[face]:
                faces[face], assigned[face] = oracle.bound_material(subset.GetPrim()), True
    return faces


def _mesh(obj: Any) -> Any:
    return obj.data
