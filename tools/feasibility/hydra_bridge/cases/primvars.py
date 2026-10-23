"""Normals, velocities, constant primvars as object properties, and dropped custom attributes, against USD."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pxr import Sdf, UsdGeom

from . import oracle
from .harness import codes

if TYPE_CHECKING:
    from .harness import Case

TIME = 1.0
NORMAL_MESHES = ("/World/Normals/Vertex", "/World/Normals/Corners", "/World/Normals/Faces", "/World/Normals/LeftHanded")
# Holder's constant primvars Blender can't hold as ID properties.
# Holder's integers beyond 32 bits, which keep their low 32 bits with a warning.
NARROWED = {"serial", "ids"}
UNHELD = {
    "decal",
    "a_primvar_name_that_is_longer_than_the_sixty_three_bytes_blender_allows",
    "proscenium_source",
}
# Dropped attributes by source, from how the scene is built; Part is warned once per instance.
DROPPED = {
    "/World/Custom/Tagged": {"myCustom", "userProp", "userProperties:note"},
    "/World/Custom/Wire": {"id"},
    "/World/KitA/Part": {"note"},
    "/World/KitB/Part": {"note"},
}


def run(case: Case) -> None:
    stage = case.open("primvars.usda")
    bridge = case.native.Bridge(stage)
    plan = case.native.build_plan(bridge.capture(TIME))
    created = case.apply_plan(plan)
    _normals(case, stage, plan, created)
    _motion(case, stage, plan, created)
    _properties(case, stage, plan, created)
    _dropped(case, stage, bridge, plan)


def _usd_normals(mesh: UsdGeom.Mesh) -> tuple[list[tuple[float, ...]], str]:
    """The normals USD uses, flattened, and their interpolation: primvars:normals wins over the attribute."""
    primvar = UsdGeom.PrimvarsAPI(mesh).GetPrimvar("normals")
    if primvar and primvar.HasAuthoredValue():
        return [oracle.components(n) for n in primvar.ComputeFlattened(TIME)], primvar.GetInterpolation()
    return [oracle.components(n) for n in mesh.GetNormalsAttr().Get(TIME)], mesh.GetNormalsInterpolation()


def _normals(case: Case, stage: Any, plan: Any, created: dict[str, Any]) -> None:
    wrong = {}
    for source in NORMAL_MESHES:
        usd = UsdGeom.Mesh(stage.GetPrimAtPath(source))
        layout = oracle.mesh_layout(usd, TIME)
        normals, interpolation = _usd_normals(usd)
        # Each Blender corner's normal: its point's, its face's, or its own USD corner's.
        if interpolation in (UsdGeom.Tokens.vertex, UsdGeom.Tokens.varying):
            expected = [normals[v] for v in layout["corner_verts"]]
        elif interpolation == UsdGeom.Tokens.uniform:
            expected = [normals[f] for f in layout["face_of_corner"]]
        else:
            expected = [normals[c] for c in layout["source_corner"]]
        mesh = created[source].data
        found = [oracle.components(n.vector) for n in mesh.corner_normals]
        if not mesh.has_custom_normals or not oracle.all_close(found, expected, 1e-5):
            wrong[source] = (mesh.has_custom_normals, found, expected)
    case.check(
        "authored normals are Blender's custom normals per point, corner (indexed, primvars:normals winning) and "
        "face, and follow the reversed corners of a left-handed mesh",
        not wrong,
        wrong,
    )
    smooth = created["/World/Normals/Smooth"].data
    case.check(
        "a subdivision surface's authored normals are ignored with a diagnostic, as USD specifies",
        not smooth.has_custom_normals and "ignored-normals" in codes(plan, "/World/Normals/Smooth"),
        (smooth.has_custom_normals, codes(plan, "/World/Normals/Smooth")),
    )


def _point_vectors(mesh: Any, name: str) -> list[tuple[float, ...]] | None:
    attribute = mesh.attributes.get(name)
    if attribute is None or attribute.domain != "POINT" or attribute.data_type != "FLOAT_VECTOR":
        return None
    return [oracle.components(d.vector) for d in attribute.data]


def _motion(case: Case, stage: Any, plan: Any, created: dict[str, Any]) -> None:
    moving = UsdGeom.Mesh(stage.GetPrimAtPath("/World/Motion/Moving"))
    mesh = created["/World/Motion/Moving"].data
    velocities = [oracle.components(v) for v in moving.GetVelocitiesAttr().Get(TIME)]
    accelerations = [oracle.components(a) for a in moving.GetAccelerationsAttr().Get(TIME)]
    found = {name: _point_vectors(mesh, name) for name in ("velocity", "velocities", "accelerations")}
    case.check(
        "velocities become Blender's velocity attribute; accelerations stay a generic attribute and are warned",
        found["velocity"] is not None
        and oracle.all_close(found["velocity"], velocities)
        and found["velocities"] is None
        and found["accelerations"] is not None
        and oracle.all_close(found["accelerations"], accelerations)
        and "no-blender-equivalent" in codes(plan, "/World/Motion/Moving"),
        (found, codes(plan, "/World/Motion/Moving")),
    )
    clash = UsdGeom.PrimvarsAPI(stage.GetPrimAtPath("/World/Motion/Clash")).GetPrimvar("velocity")
    own = [oracle.components(v) for v in clash.ComputeFlattened(TIME)]
    velocity = _point_vectors(created["/World/Motion/Clash"].data, "velocity")
    case.check(
        "a primvar named velocity keeps the name, and velocities are skipped with a name-collision warning",
        velocity is not None
        and oracle.all_close(velocity, own)
        and "name-collision" in codes(plan, "/World/Motion/Clash"),
        (velocity, own, codes(plan, "/World/Motion/Clash")),
    )


def _expected_property(value: Any) -> Any:
    """A USD value as Blender's ID property, by the plan's rule.

    A one-element array is its element, a vector a list, and an array of vectors or a matrix a list of lists (rows).
    Integers keep their low 32 bits.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return (value + 2**31) % 2**32 - 2**31
    if hasattr(value, "GetRow"):  # Gf matrices don't iterate
        return [list(value.GetRow(row)) for row in range(len(value))]
    if isinstance(value, str | bool | int | float):
        return value
    elements = list(value)
    if type(value).__name__.endswith("Array"):
        return _expected_property(elements[0]) if len(elements) == 1 else [_expected_property(e) for e in elements]
    return elements  # a Gf vector


def _blender_value(value: Any) -> Any:
    if hasattr(value, "to_list"):
        return value.to_list()
    if isinstance(value, list):
        return [_blender_value(v) for v in value]
    return value


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        return isinstance(a, list) and isinstance(b, list) and len(a) == len(b) and all(map(_same, a, b))
    if isinstance(a, float) or isinstance(b, float):
        return type(a) is type(b) and abs(a - b) < 1e-6
    return type(a) is type(b) and a == b


def _properties(case: Case, stage: Any, plan: Any, created: dict[str, Any]) -> None:
    holder = created["/World/Holder"]
    wrong = {}
    for primvar in UsdGeom.PrimvarsAPI(stage.GetPrimAtPath("/World/Holder")).GetAuthoredPrimvars():
        name = primvar.GetPrimvarName()
        if name in UNHELD:
            continue
        expected = _expected_property(primvar.ComputeFlattened(TIME))
        found = _blender_value(holder.get(name))
        if not _same(found, expected):
            wrong[name] = (found, expected)
    case.check(
        "constant primvars are ID properties on the object by name: scalars, strings, tokens, vectors, "
        "one-element arrays as their element, arrays, string arrays, arrays of vectors and matrices as rows, "
        "and integers beyond 32 bits wrapped to their low 32 bits",
        not wrong,
        wrong,
    )

    def warned_for(code: str) -> set[str]:
        return {
            d["message"].split("'")[1] for d in plan.diagnostics if d["source"] == "/World/Holder" and d["code"] == code
        }

    warned = warned_for("untransferred-primvar")
    case.check(
        "a constant primvar wrapped to 32 bits is warned, once for an array however many elements it wraps",
        warned_for("narrowed-primvar") == NARROWED
        and sum(d["code"] == "narrowed-primvar" for d in plan.diagnostics) == len(NARROWED),
        warned_for("narrowed-primvar"),
    )
    # proscenium_source is the bridge's own property, which must keep its value.
    present = {name for name in UNHELD - {"proscenium_source"} if name in holder}
    case.check(
        "constant primvars Blender can't hold (an asset path, a name over 63 bytes, the proscenium_ prefix) are "
        "warned and not authored",
        warned == UNHELD and not present and holder["proscenium_source"] == "/World/Holder",
        (warned, present),
    )
    parts = {
        source: {name: _blender_value(created[source].get(name)) for name in ("tint", "gloss")}
        for source in ("/World/KitA/Part", "/World/KitB/Part")
    }
    expected = {
        source: {
            name: _expected_property(oracle.inherited_primvar(stage, source, name, TIME)) for name in ("tint", "gloss")
        }
        for source in parts
    }
    case.check(
        "each instance's object gets its instance root's constant primvars as properties, and keeps its own",
        all(_same(parts[s][n], expected[s][n]) for s in parts for n in ("tint", "gloss"))
        and parts["/World/KitB/Part"]["gloss"] != 0.9,
        (parts, expected),
    )


def _dropped_names(plan: Any) -> dict[str, set[str]]:
    return {
        d["source"]: set(d["message"].rsplit(": ", 1)[1].split(", "))
        for d in plan.diagnostics
        if d["code"] == "dropped-attribute"
    }


def _dropped(case: Case, stage: Any, bridge: Any, plan: Any) -> None:
    dropped = _dropped_names(plan)
    case.check(
        "authored attributes UsdImaging drops are warned on meshes, placeholders and prototype prims (per "
        "instance); unauthored, applied-schema, transform-op and subset-family attributes are not",
        dropped == DROPPED,
        dropped,
    )
    plain = stage.GetPrimAtPath("/World/Custom/Plain")
    plain.CreateAttribute("added", Sdf.ValueTypeNames.Float, custom=True).Set(1.0)
    added = _dropped_names(case.native.build_plan(bridge.capture(TIME, incremental=True)))
    plain.RemoveProperty("added")
    removed = _dropped_names(case.native.build_plan(bridge.capture(TIME, incremental=True)))
    case.check(
        "adding and removing a custom attribute updates the warning in an incremental capture",
        added.get("/World/Custom/Plain") == {"added"} and "/World/Custom/Plain" not in removed,
        (added.get("/World/Custom/Plain"), removed.get("/World/Custom/Plain")),
    )
