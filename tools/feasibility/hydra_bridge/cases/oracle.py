"""Expected values from USD itself (UsdGeom, UsdShade), never from Hydra; shared by the prototype and Phase C probes."""

from __future__ import annotations

from typing import Any

from pxr import Usd, UsdGeom, UsdShade

# Hydra names the default purpose "geometry".
HYDRA_PURPOSE = {"default": "geometry", "proxy": "proxy", "render": "render", "guide": "guide"}


def drawn_gprims(stage: Usd.Stage) -> dict[str, tuple[str, ...]]:
    """Every gprim USD draws, through instance proxies, with its native instance roots, outermost first.

    A point instancer's prototypes are drawn only as its instances, so they're left out.
    """
    result = {}
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies(Usd.PrimDefaultPredicate)):
        if _under_point_instancer(prim):
            continue
        if prim.IsA(UsdGeom.Gprim):  # ty: ignore[no-matching-overload] - IsA also takes a schema class
            roots = []
            ancestor = prim.GetParent()
            while ancestor and not ancestor.IsPseudoRoot():
                if ancestor.IsInstance():
                    roots.append(str(ancestor.GetPath()))
                ancestor = ancestor.GetParent()
            result[str(prim.GetPath())] = tuple(reversed(roots))
    return result


def _under_point_instancer(prim: Usd.Prim) -> bool:
    ancestor = prim.GetParent()
    while ancestor and not ancestor.IsPseudoRoot():
        if ancestor.IsA(UsdGeom.PointInstancer):  # ty: ignore[no-matching-overload] - IsA also takes a schema class
            return True
        ancestor = ancestor.GetParent()
    return False


def world(stage: Usd.Stage, source: str, time: float) -> Any:
    return UsdGeom.XformCache(time).GetLocalToWorldTransform(stage.GetPrimAtPath(source))


def close(a: Any, b: Any, tolerance: float = 1e-5) -> bool:
    """Element-wise comparison of two 4x4 matrices."""
    return all(abs(a[row][col] - b[row][col]) < tolerance for row in range(4) for col in range(4))


def display_color(stage: Usd.Stage, source: str, time: float) -> Any:
    return inherited_primvar(stage, source, "displayColor", time)


def inherited_primvar(stage: Usd.Stage, source: str, name: str, time: float) -> Any:
    """A constant primvar's value as the prim sees it: its own, else the nearest ancestor's, flattened."""
    primvar = UsdGeom.PrimvarsAPI(stage.GetPrimAtPath(source)).FindPrimvarWithInheritance(name)
    return primvar.ComputeFlattened(time) if primvar and primvar.HasAuthoredValue() else None


def visible(stage: Usd.Stage, source: str, time: float) -> bool:
    """Effective visibility for the prim's own purpose, which is what the plan reports.

    A guide counts only when explicitly visible (spec VIS-04): its result can be "inherited" when that is the
    nearest authored opinion, which doesn't make it visible.
    """
    imageable = UsdGeom.Imageable(stage.GetPrimAtPath(source))
    purpose = imageable.ComputePurpose()
    effective = imageable.ComputeEffectiveVisibility(purpose, time)
    if purpose == UsdGeom.Tokens.guide:
        return effective == UsdGeom.Tokens.visible
    return effective != UsdGeom.Tokens.invisible


def purpose(stage: Usd.Stage, source: str) -> str:
    return HYDRA_PURPOSE[str(UsdGeom.Imageable(stage.GetPrimAtPath(source)).ComputePurpose())]


def placeholder_bounds(stage: Usd.Stage, source: str, time: float) -> tuple[Any, Any] | None:
    """A placeholder's usable bounds: the authored extent, else USD's computed extent for a point-based prim
    that isn't drawn as a mesh (curves, points). Point instancers and volumes get none without an authored
    extent, since computing theirs means evaluating prototypes or reading field files."""
    prim = stage.GetPrimAtPath(source)
    boundable = UsdGeom.Boundable(prim)
    extent = boundable.GetExtentAttr()
    if extent.HasAuthoredValue():
        return tuple(extent.Get(time))
    if prim.IsA(UsdGeom.PointBased) and not prim.IsA(UsdGeom.Mesh) and not prim.IsA(UsdGeom.NurbsPatch):  # ty: ignore[no-matching-overload] - IsA also takes a schema class
        computed = UsdGeom.Boundable.ComputeExtentFromPlugins(boundable, time)
        return tuple(computed) if computed else None
    return None


def bound_material(prim: Usd.Prim, material_purpose: str = "") -> str | None:
    purpose_token = material_purpose or UsdShade.Tokens.allPurpose
    material = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial(purpose_token)[0]
    return str(material.GetPath()) if material else None


def binds_without_api(prim: Usd.Prim) -> bool:
    """Whether the prim authors a material:binding relationship without MaterialBindingAPI applied."""
    return not prim.HasAPI(UsdShade.MaterialBindingAPI) and any(  # ty: ignore[no-matching-overload] - HasAPI also takes a schema class
        rel.GetName().startswith("material:binding") and rel.HasAuthoredTargets() for rel in prim.GetRelationships()
    )


def face_materials(stage: Usd.Stage, source: str, time: float, material_purpose: str = "") -> list[str | None]:
    """Each face's bound material: its materialBind subset's, else the mesh's, as UsdShade assigns them."""
    mesh = UsdGeom.Mesh(stage.GetPrimAtPath(source))
    faces = [bound_material(mesh.GetPrim(), material_purpose)] * len(mesh.GetFaceVertexCountsAttr().Get(time) or [])
    for subset in UsdShade.MaterialBindingAPI(mesh.GetPrim()).GetMaterialBindSubsets():
        if subset.GetElementTypeAttr().Get() != UsdGeom.Tokens.face:
            continue
        for face in subset.GetIndicesAttr().Get(time) or []:
            if 0 <= face < len(faces):
                faces[face] = bound_material(subset.GetPrim(), material_purpose)
    return faces


def plan_face_materials(plan: Any, obj: dict[str, Any]) -> list[set[str] | None]:
    """Each face's material in the plan, as the set of USD sources of its material (None for no material)."""
    mesh = plan.meshes[obj["mesh"]]
    slots = obj["material_slots"]
    materials = plan.materials
    return [
        None if slots[slot] is None else set(materials[slots[slot]]["sources"]) for slot in mesh["material_indices"]
    ]


def materials_match(expected: list[str | None], planned: list[set[str] | None], exact: bool = False) -> bool:
    """A planned face matches when its material's sources include the USD-bound material (or both are None).

    With `exact`, the sources must be that material alone, which holds outside instancing: a plan material
    has one source per drawn copy, so only an instanced material has several.
    """
    if len(expected) != len(planned):
        return False

    def match(e: str | None, p: set[str] | None) -> bool:
        if e is None or p is None:
            return e is None and p is None
        return p == {e} if exact else e in p

    return all(match(e, p) for e, p in zip(expected, planned, strict=True))


def mesh_layout(mesh: Any, time: float) -> dict[str, Any]:
    """From USD alone: each face's points, and for each Blender corner its USD corner, face and point.

    A left-handed face is reversed after its first corner, which keeps its winding right-handed in Blender.
    """
    counts = list(mesh.GetFaceVertexCountsAttr().Get(time))
    indices = list(mesh.GetFaceVertexIndicesAttr().Get(time))
    left = mesh.GetOrientationAttr().Get() == UsdGeom.Tokens.leftHanded
    source_corner, face_of_corner, usd_faces = [], [], []
    offset = 0
    for face, count in enumerate(counts):
        usd_faces.append(indices[offset : offset + count])
        for j in range(count):
            source_corner.append(offset + (count - j if left and j else j))
            face_of_corner.append(face)
        offset += count
    return {
        "source_corner": source_corner,
        "face_of_corner": face_of_corner,
        "corner_verts": [indices[c] for c in source_corner],
        "usd_faces": usd_faces,
        "points": len(mesh.GetPointsAttr().Get(time)),
        "faces": len(counts),
    }


def on_domain(flattened: list[Any], interpolation: str, texcoord: bool, layout: dict[str, Any]) -> list[Any]:
    """A flattened primvar's values on its Blender domain, in Blender's element order."""
    if interpolation == UsdGeom.Tokens.faceVarying:
        return [flattened[c] for c in layout["source_corner"]]
    if not texcoord:
        return flattened  # points and faces keep USD's order
    if interpolation == UsdGeom.Tokens.uniform:
        return [flattened[f] for f in layout["face_of_corner"]]
    return [flattened[v] for v in layout["corner_verts"]]  # vertex and varying


def components(value: Any) -> tuple[float, ...]:
    try:
        return tuple(float(component) for component in value)
    except TypeError:
        return (float(value),)


def element_value(element: Any) -> tuple[float, ...]:
    for name in ("color", "vector", "value"):
        if hasattr(element, name):
            return components(getattr(element, name))
    raise TypeError(f"unknown attribute element {element!r}")


def all_close(a: list[tuple[float, ...]], b: list[tuple[float, ...]], tolerance: float = 1e-6) -> bool:
    return len(a) == len(b) and all(
        len(x) == len(y) and all(abs(p - q) < tolerance for p, q in zip(x, y, strict=True))
        for x, y in zip(a, b, strict=True)
    )
