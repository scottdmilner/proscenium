"""M4's object baseline (M04-prototypes plan, B1): the structure M1b's bridge and apply.py build in Blender.

One object per drawn copy and destination, sharing only equivalent geometry, with each destination's hide flag,
materials, and world transform, on the two feasibility fixtures; and each case's appearance values where the
baseline stores them (B4). Expected values come from how the fixtures are built and from UsdGeom and UsdShade.
Values that need translation, such as reader fallbacks, non-constant opacity, and texture sampling, are M8's and M9's.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pxr import Gf, Sdf, Tf, Usd, UsdGeom, UsdShade

from fixtures import appearance

from .harness import Runtime, run_isolated

if TYPE_CHECKING:
    from collections.abc import Generator

BODY = Path(__file__).parent / "bodies/baseline.py"
MESH = Tf.Type.Find(UsdGeom.Mesh)
# Each destination's material purpose, as GRAM-12 settles: preview in the viewport, full in the final render.
PURPOSES = {"viewport": UsdShade.Tokens.preview, "render": UsdShade.Tokens.full}
# Blender's domain for each primvar interpolation the cases use.
DOMAINS = {"uniform": "FACE", "vertex": "POINT", "varying": "POINT", "faceVarying": "CORNER"}
# Tolerance for values that crossed Blender's float32 storage.
CLOSE = 1e-6


@dataclass(frozen=True)
class BaselineScene:
    """A fixture's scene, with the drawn meshes each destination shows, as the fixture is built."""

    root: Path
    stage: Usd.Stage
    shown: dict[str, frozenset[str]]  # destination -> drawn meshes it shows
    facts: appearance.AppearanceScene | appearance.StressScene  # the fixture's own


@pytest.fixture(params=["appearance", "stress"])
def scene(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[BaselineScene]:
    if request.param == "appearance":
        with appearance.appearance_cases(tmp_path) as cases:
            # Every mesh in the appearance scene is visible with default purpose.
            drawn = frozenset(_drawn(cases.stage))
            yield BaselineScene(cases.root, cases.stage, {"viewport": drawn, "render": drawn}, cases)
    else:
        with appearance.nested_stress(tmp_path) as stress:
            shown = {"viewport": stress.viewport, "render": stress.render}
            yield BaselineScene(stress.root, stress.stage, shown, stress)


@pytest.fixture
def result(scene: BaselineScene, wheel: Runtime, hydra_bridge: Path, tmp_path: Path) -> dict[str, Any]:
    result = run_isolated(wheel, BODY, "apply_scene", tmp_path, module_dir=str(hydra_bridge), scene=str(scene.root))
    assert result["errors"] == []
    return result


@pytest.fixture
def applied(result: dict[str, Any]) -> list[dict[str, Any]]:
    return result["objects"]


def _drawn(stage: Usd.Stage) -> dict[str, Usd.Prim]:
    """Every mesh USD draws, one per copy: instance contents through their proxies."""
    prims = Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())
    return {str(p.GetPath()): p for p in prims if p.IsA(MESH)}


def _instance_context(prim: Usd.Prim) -> list[str]:
    """The native instance roots above a drawn copy, outermost first."""
    roots = [str(p.GetPath()) for p in _ancestors(prim) if p.IsInstance()]
    return roots[::-1]


def _ancestors(prim: Usd.Prim) -> Generator[Usd.Prim]:
    prim = prim.GetParent()
    while prim and not prim.IsPseudoRoot():
        yield prim
        prim = prim.GetParent()


def _resets_in_instance(prim: Usd.Prim) -> bool:
    """Whether a drawn copy or an ancestor below its nearest instance root resets the transform stack."""
    while prim and not prim.IsPseudoRoot() and not prim.IsInstance():
        if UsdGeom.Xformable(prim).GetResetXformStack():
            return True
        prim = prim.GetParent()
    return False


def _bound(prim: Usd.Prim, purpose: str) -> str | None:
    material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial(purpose)
    return str(material.GetPath()) if material else None


def _face_materials(prim: Usd.Prim, purpose: str) -> list[str | None]:
    """Each face's material for one material purpose: its materialBind subset's, or else the mesh's."""
    faces = len(UsdGeom.Mesh(prim).GetFaceVertexCountsAttr().Get())
    shown = [_bound(prim, purpose)] * faces
    for subset in UsdShade.MaterialBindingAPI(prim).GetMaterialBindSubsets():
        for face in subset.GetIndicesAttr().Get():
            shown[face] = _bound(subset.GetPrim(), purpose)
    return shown


def _by_source(objects: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obj in objects:
        grouped[obj["source"]].append(obj)
    return grouped


def test_one_object_per_drawn_copy_and_destination(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    drawn = _drawn(scene.stage)
    grouped = _by_source(applied)
    assert set(grouped) == set(drawn)
    for path, objects in grouped.items():
        for destination, shown in scene.shown.items():
            displaying = [o for o in objects if o[destination]]
            assert len(displaying) == (1 if path in shown else 0), (path, destination)
        if any(path in shown for shown in scene.shown.values()):
            assert all(o["viewport"] or o["render"] for o in objects), path
        else:  # a copy shown in neither destination still has one object, for correspondence
            assert len(objects) == 1, path
        for obj in objects:
            assert obj["instance_context"] == _instance_context(drawn[path]), path
            assert obj["placeholder"] is None, path
            assert obj["mesh"] is not None, path


def test_materials_per_destination(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    drawn = _drawn(scene.stage)
    for obj in applied:
        prim = drawn[obj["source"]]
        for destination, purpose in PURPOSES.items():
            if not obj[destination]:
                continue
            expected = _face_materials(prim, purpose)
            shown = [obj["slots"][slot] for slot in obj["face_slots"]]
            assert len(shown) == len(expected), obj["source"]
            for face, (sources, material) in enumerate(zip(shown, expected, strict=True)):
                assert (sources is None) == (material is None), (obj["source"], destination, face)
                assert material is None or material in sources, (obj["source"], destination, face, sources)


def _mesh_content(prim: Usd.Prim) -> tuple[object, ...]:
    """What a drawn copy's Blender mesh holds, from USD: everything per copy is on its object instead.

    Points, topology and orientation, each face's material slot (its first materialBind subset, by path, or the
    mesh's own), the non-constant primvars and normals, and the subdivision scheme and sidedness.
    """
    mesh = UsdGeom.Mesh(prim)
    faces = len(mesh.GetFaceVertexCountsAttr().Get())
    subsets = sorted(UsdShade.MaterialBindingAPI(prim).GetMaterialBindSubsets(), key=lambda s: s.GetPrim().GetPath())
    slots = [0] * faces
    for slot, subset in enumerate(subsets, 1):
        for face in subset.GetIndicesAttr().Get():
            slots[face] = slots[face] or slot
    primvars = sorted(
        (pv.GetPrimvarName(), str(pv.GetTypeName()), pv.GetInterpolation(), tuple(pv.ComputeFlattened()))
        for pv in UsdGeom.PrimvarsAPI(prim).GetPrimvars()
        if pv.HasAuthoredValue() and pv.GetInterpolation() != UsdGeom.Tokens.constant
    )
    normals = mesh.GetNormalsAttr().Get()
    return (
        tuple(mesh.GetPointsAttr().Get()),
        tuple(mesh.GetFaceVertexCountsAttr().Get()),
        tuple(mesh.GetFaceVertexIndicesAttr().Get()),
        mesh.GetOrientationAttr().Get(),
        (len(subsets) + 1, tuple(slots)),
        tuple(primvars),
        None if normals is None else tuple(normals),
        mesh.GetSubdivisionSchemeAttr().Get(),
        mesh.GetDoubleSidedAttr().Get(),
    )


def test_meshes_shared_exactly_among_equal_content(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    # The sharing criteria (B5, SHARE-06): copies share a mesh exactly when their mesh content is equal, so the
    # fixture's equivalent uses share one (PVAR-04, PVAR-05), and so does a mesh differing only in a constant
    # primvar, which is on its object.
    drawn = _drawn(scene.stage)
    content: dict[str, set[tuple[object, ...]]] = defaultdict(set)
    for obj in applied:
        content[obj["mesh"]].add(_mesh_content(drawn[obj["source"]]))
    assert all(len(held) == 1 for held in content.values()), content  # a shared mesh holds one content
    held = [next(iter(c)) for c in content.values()]
    assert len(set(held)) == len(held)  # and no two meshes hold the same
    if isinstance(scene.facts, appearance.AppearanceScene):
        meshes = {obj["source"]: obj["mesh"] for obj in applied}
        for uses in scene.facts.shared:
            assert len({meshes[use] for use in uses}) == 1, uses


def test_world_transforms_match_usdgeom(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    # Shear, negative and nonuniform scale, and a reset stack inside instances (XFORM-01 to XFORM-03), in the plan.
    drawn = _drawn(scene.stage)
    cache = UsdGeom.XformCache()
    wrong = [
        o["source"]
        for o in applied
        if not Gf.IsClose(Gf.Matrix4d(o["plan_world"]), cache.GetLocalToWorldTransform(drawn[o["source"]]), 1e-6)
    ]
    assert not wrong


def _sheared(world: Gf.Matrix4d) -> bool:
    """Whether a world transform's axes aren't orthogonal: its rows, in USD's row-vector convention."""
    axes = [world.GetRow3(i) for i in range(3)]
    return any(
        abs(Gf.Dot(axes[i], axes[j])) > 1e-6 * axes[i].GetLength() * axes[j].GetLength()
        for i, j in ((0, 1), (0, 2), (1, 2))
    )


def test_blender_world_transforms_match_usdgeom(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    # What Blender composes once the depsgraph evaluates each object: a sheared copy through its parent empty,
    # which only sheared copies have (XFORM-03).
    drawn = _drawn(scene.stage)
    cache = UsdGeom.XformCache()
    wrong = []
    for obj in applied:
        usd = cache.GetLocalToWorldTransform(drawn[obj["source"]])
        if not Gf.IsClose(Gf.Matrix4d(obj["world"]), usd, 1e-5):
            wrong.append(obj["source"])
        assert obj["shear_parent"] == (obj["source"] if _sheared(usd) else None), obj["source"]
    assert not wrong


def test_known_gap_hydra_ignores_a_reset_inside_an_instance(scene: BaselineScene, result: dict[str, Any]) -> None:
    # WORKAROUND for OpenUSD #862 (ResetsBelow in the bridge's instancing.h): Hydra's own composition, a copy's
    # flattened transform then its instance's, is wrong exactly for the copies under a reset inside an instance.
    # This fails once Hydra honors the reset, and the workaround can go.
    drawn = _drawn(scene.stage)
    cache = UsdGeom.XformCache()
    hydra = result["hydra_world"]
    wrong = {
        s
        for s, rows in hydra.items()
        if not Gf.IsClose(Gf.Matrix4d(rows), cache.GetLocalToWorldTransform(drawn[s]), 1e-6)
    }
    assert hydra
    assert wrong == {s for s in hydra if _resets_in_instance(drawn[s])}


# --- Appearance values where the baseline stores them (B4) ---------------------------------------------------


def _close(a: Any, b: Any) -> bool:
    """Equal within CLOSE, element by element, for numbers and (nested) sequences."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= CLOSE
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        return False
    return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b, strict=True))


def _rgb(values: list[list[float]]) -> list[list[float]]:
    return [v[:3] for v in values]


def _check_primvar_storage(obj: dict[str, Any], name: str, authored: tuple[str, tuple[Any, ...]] | None) -> None:
    """A constant value is an ID property of the copy's object; any other is a mesh attribute on its domain."""
    where = (obj["source"], name)
    if authored is None:
        assert name not in obj["properties"] and name not in obj["attributes"], where
        return
    interpolation, values = authored
    if interpolation == "constant":
        assert _close(obj["properties"].get(name), values[0]), (where, obj["properties"].get(name))
        assert name not in obj["attributes"], where
        return
    attribute = obj["attributes"].get(name)
    assert attribute is not None and attribute["domain"] == DOMAINS[interpolation], (where, attribute)
    stored = attribute["values"]
    assert _close(_rgb(stored) if attribute["data_type"] == "FLOAT_COLOR" else stored, list(values)), where


@pytest.mark.parametrize("scene", ["appearance"], indirect=True)
def test_display_color_and_opacity_where_stored(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    # Mesh and inherited display color (PVAR-07, PVAR-08, GRAM-05), through nested instances: each copy's own values.
    # A constant color and opacity are also the object's color and alpha; nothing displays any other opacity yet (M8).
    facts = scene.facts
    assert isinstance(facts, appearance.AppearanceScene)
    grouped = _by_source(applied)
    for mesh, color in facts.display_color.items():
        for obj in grouped[mesh]:
            _check_primvar_storage(obj, "displayColor", color)
            _check_primvar_storage(obj, "displayOpacity", facts.display_opacity[mesh])
            if color[0] == "constant":
                assert _close(obj["color"][:3], color[1][0]), (mesh, obj["color"])
            opacity = facts.display_opacity[mesh]
            alpha = opacity[1][0] if opacity is not None and opacity[0] == "constant" else 1.0
            assert _close(obj["color"][3], alpha), (mesh, obj["color"])


@pytest.mark.parametrize("scene", ["appearance"], indirect=True)
def test_reader_primvars_reach_each_copy(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    # Instance primvars for materials (PVAR-09, GRAM-08, GRAM-11): each copy's own value, inherited from its
    # instance root, is an ID property of its object, which an Attribute node of type Object reads. A copy with
    # none has no property, where its reader's fallback must come from the translated material (M9).
    facts = scene.facts
    assert isinstance(facts, appearance.AppearanceScene)
    drawn = _drawn(scene.stage)
    grouped = _by_source(applied)
    for (mesh, name), shown in facts.reader_values.items():
        primvar = UsdGeom.PrimvarsAPI(drawn[mesh]).FindPrimvarWithInheritance(name)
        own = primvar.Get() if primvar and primvar.HasAuthoredValue() else None
        if own is not None:
            own = own[0] if name == "displayColor" else own  # displayColor is an array
            assert _close(list(own) if not isinstance(own, float) else own, shown), (mesh, name)
        for obj in grouped[mesh]:
            stored = obj["properties"].get(name)
            if own is None:
                assert stored is None, (mesh, name, stored)
            else:
                assert _close(stored, shown), (mesh, name, stored)


def _usd_corners(prim: Usd.Prim, primvar: UsdGeom.Primvar) -> list[Any]:
    """A primvar's flattened values, one per face corner, in USD's face-vertex order."""
    values = primvar.ComputeFlattened()
    if primvar.GetInterpolation() == "faceVarying":
        return [list(v) for v in values]
    indices = UsdGeom.Mesh(prim).GetFaceVertexIndicesAttr().Get()
    return [list(values[i]) for i in indices]  # vertex or varying: by point


@pytest.mark.parametrize("scene", ["appearance"], indirect=True)
def test_uv_maps(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    # Named UVs (PVAR-06): each UV set is a UV map with its primvar's name and its values at every corner.
    facts = scene.facts
    assert isinstance(facts, appearance.AppearanceScene)
    drawn = _drawn(scene.stage)
    grouped = _by_source(applied)
    for mesh, uv_sets in facts.uv_sets[()].items():
        prim = drawn[mesh]
        primvars = UsdGeom.PrimvarsAPI(prim)
        # Known difference, M8's: the baseline makes every float2[] primvar with a per-corner or per-point
        # interpolation a UV map, as UV-set names would, where USD's typing (the default) takes none.
        extras = {
            pv.GetPrimvarName()
            for pv in primvars.GetPrimvars()
            if pv.GetTypeName() == Sdf.ValueTypeNames.Float2Array and pv.GetInterpolation() in DOMAINS
        }
        for obj in grouped[mesh]:
            assert obj["corner_verts"] == list(UsdGeom.Mesh(prim).GetFaceVertexIndicesAttr().Get()), mesh
            assert set(obj["uv_maps"]) == set(uv_sets) | extras, (mesh, obj["uv_maps"])
            for name in uv_sets:
                stored = obj["attributes"][name]
                assert stored["domain"] == "CORNER", (mesh, name)
                assert _close(stored["values"], _usd_corners(prim, primvars.GetPrimvar(name))), (mesh, name)


@pytest.mark.parametrize("scene", ["stress"], indirect=True)
def test_stress_display_color_per_copy(scene: BaselineScene, applied: list[dict[str, Any]]) -> None:
    # Nested instances with differing appearance (F-NESTED-STRESS): each copy's inherited constant color.
    facts = scene.facts
    assert isinstance(facts, appearance.StressScene)
    grouped = _by_source(applied)
    for mesh, color in facts.display_color.items():
        for obj in grouped[mesh]:
            _check_primvar_storage(obj, "displayColor", None if color is None else ("constant", (color,)))
