"""The appearance fixtures produce what they claim, as USD's own APIs read their scenes."""

from __future__ import annotations

import fnmatch
from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Sdf, Tf, Usd, UsdGeom, UsdShade

from fixtures import appearance

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from fixtures.appearance import AppearanceScene, StressScene

MESH, SHADER = Tf.Type.Find(UsdGeom.Mesh), Tf.Type.Find(UsdShade.Shader)
UV_INTERPOLATIONS = {UsdGeom.Tokens.vertex, UsdGeom.Tokens.varying, UsdGeom.Tokens.faceVarying}


@pytest.fixture
def cases(tmp_path: Path) -> Generator[AppearanceScene]:
    with appearance.appearance_cases(tmp_path) as scene:
        yield scene


@pytest.fixture
def stress(tmp_path: Path) -> Generator[StressScene]:
    with appearance.nested_stress(tmp_path) as scene:
        yield scene


def _meshes(stage: Usd.Stage, root: str) -> list[Usd.Prim]:
    """Every mesh under `root`, one per drawn copy: instance contents through their proxies."""
    prims = Usd.PrimRange(stage.GetPrimAtPath(root), Usd.TraverseInstanceProxies())
    return [p for p in prims if p.IsA(MESH)]


def _inherited(prim: Usd.Prim, name: str) -> UsdGeom.Primvar | None:
    """The primvar `prim` shows: its own authored one, or the nearest ancestor's constant one."""
    primvar = UsdGeom.PrimvarsAPI(prim).FindPrimvarWithInheritance(name)
    return primvar if primvar and primvar.HasAuthoredValue() else None


def _bound(prim: Usd.Prim, purpose: str) -> str | None:
    material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial(purpose)
    return str(material.GetPath()) if material else None


def _shaders(material: UsdShade.Material, shader_id: str) -> list[UsdShade.Shader]:
    return [
        UsdShade.Shader(p)
        for p in Usd.PrimRange(material.GetPrim())
        if p.IsA(SHADER) and UsdShade.Shader(p).GetIdAttr().Get() == shader_id
    ]


def _content(prim: Usd.Prim) -> tuple[object, ...]:
    """What makes two meshes outside instances equivalent uses: topology, points, primvars, scheme, and sidedness."""
    mesh = UsdGeom.Mesh(prim)
    primvars = sorted(
        (pv.GetPrimvarName(), str(pv.GetTypeName()), pv.GetInterpolation(), tuple(pv.ComputeFlattened()))
        for pv in UsdGeom.PrimvarsAPI(prim).GetPrimvars()
        if pv.HasAuthoredValue()
    )
    counts, indices = mesh.GetFaceVertexCountsAttr().Get(), mesh.GetFaceVertexIndicesAttr().Get()
    scheme, sided = mesh.GetSubdivisionSchemeAttr().Get(), mesh.GetDoubleSidedAttr().Get()
    return (tuple(counts), tuple(indices), tuple(mesh.GetPointsAttr().Get()), tuple(primvars), scheme, sided)


def _sharing_key(prim: Usd.Prim) -> object:
    # Copies of one prototype mesh are the same prim in the prototype; other meshes compare by content.
    return prim.GetPrimInPrototype().GetPath() if prim.IsInstanceProxy() else _content(prim)


def _uv_sets(prim: Usd.Prim, names: tuple[str, ...]) -> frozenset[str]:
    """The UV sets of a mesh under UV-set names, by spec/support/geometry.md#supported-geometry."""
    found = set()
    for pv in UsdGeom.PrimvarsAPI(prim).GetPrimvars():
        name, type_name = pv.GetPrimvarName(), pv.GetTypeName()
        if type_name == Sdf.ValueTypeNames.TexCoord2fArray:
            found.add(name)
        elif type_name == Sdf.ValueTypeNames.Float2Array and pv.GetInterpolation() in UV_INTERPOLATIONS:
            if any(fnmatch.fnmatchcase(name.casefold(), glob.casefold()) for glob in names):
                found.add(name)
    return frozenset(found)


# --- F-APPEARANCE-CASES -------------------------------------------------------------------------------


def test_shared_sets_are_the_equivalent_uses(cases: AppearanceScene) -> None:
    drawn = {str(p.GetPath()): p for root in cases.shared_roots for p in _meshes(cases.stage, root)}
    assert set().union(*cases.shared) == set(drawn)
    keys = [{_sharing_key(drawn[path]) for path in uses} for uses in cases.shared]
    assert all(len(k) == 1 for k in keys)  # each set's uses are equivalent
    assert len({next(iter(k)) for k in keys}) == len(keys)  # and no two sets are


def test_display_color_and_opacity(cases: AppearanceScene) -> None:
    for name, expected in (("displayColor", cases.display_color), ("displayOpacity", cases.display_opacity)):
        for path, shown in expected.items():
            primvar = _inherited(cases.stage.GetPrimAtPath(path), name)
            if shown is None:
                assert primvar is None, path
                continue
            assert primvar is not None, path
            interpolation, values = shown
            assert primvar.GetInterpolation() == interpolation, path
            assert [tuple(v) if name == "displayColor" else v for v in primvar.ComputeFlattened()] == pytest.approx(
                list(values)
            ), path


def test_bound_material_per_destination(cases: AppearanceScene) -> None:
    for path, (viewport, render) in cases.materials.items():
        prim = cases.stage.GetPrimAtPath(path)
        assert prim, path
        assert (_bound(prim, UsdShade.Tokens.preview), _bound(prim, UsdShade.Tokens.full)) == (viewport, render), path


def test_every_mesh_has_a_material_fact(cases: AppearanceScene) -> None:
    drawn = {str(p.GetPath()) for p in _meshes(cases.stage, "/World")}
    assert set(cases.materials) | set(cases.face_materials) == drawn


def test_face_materials(cases: AppearanceScene) -> None:
    for path, expected in cases.face_materials.items():
        prim = cases.stage.GetPrimAtPath(path)
        faces = len(UsdGeom.Mesh(prim).GetFaceVertexCountsAttr().Get())
        shown: list[str | None] = [_bound(prim, UsdShade.Tokens.preview)] * faces
        for subset in UsdShade.MaterialBindingAPI(prim).GetMaterialBindSubsets():
            for face in subset.GetIndicesAttr().Get():
                shown[face] = _bound(subset.GetPrim(), UsdShade.Tokens.preview)
        assert tuple(shown) == expected, path


def test_reader_values(cases: AppearanceScene) -> None:
    for (path, name), expected in cases.reader_values.items():
        prim = cases.stage.GetPrimAtPath(path)
        material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial(UsdShade.Tokens.preview)
        readers = [
            s
            for shader_id in ("UsdPrimvarReader_float", "UsdPrimvarReader_float3")
            for s in _shaders(material, shader_id)
            if s.GetInput("varname").Get() == name
        ]
        assert len(readers) == 1, (path, name)
        primvar = _inherited(prim, name)
        if primvar is None:
            value = readers[0].GetInput("fallback").Get()
        else:
            value = primvar.ComputeFlattened()
            value = value[0] if primvar.GetTypeName().isArray else value  # a constant array holds one value
        shown = tuple(value) if isinstance(expected, tuple) else value
        assert shown == pytest.approx(expected), (path, name)


def test_string_values(cases: AppearanceScene) -> None:
    for (path, name), expected in cases.string_values.items():
        primvar = _inherited(cases.stage.GetPrimAtPath(path), name)
        assert primvar is not None and primvar.GetInterpolation() == "constant", (path, name)
        assert primvar.Get() == expected, (path, name)


def test_uv_sets(cases: AppearanceScene) -> None:
    for names, meshes in cases.uv_sets.items():
        for path, expected in meshes.items():
            assert _uv_sets(cases.stage.GetPrimAtPath(path), names) == expected, (names, path)


def test_texture_uvs(cases: AppearanceScene) -> None:
    for path, uv_set in cases.texture_uvs.items():
        prim = cases.stage.GetPrimAtPath(path)
        material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial(UsdShade.Tokens.preview)
        (texture,) = _shaders(material, "UsdUVTexture")
        (source,) = texture.GetInput("st").GetConnectedSources()[0]
        reader = UsdShade.Shader(source.source.GetPrim())
        assert reader.GetIdAttr().Get() == "UsdPrimvarReader_float2"
        assert reader.GetInput("varname").Get() == uv_set
        assert UsdGeom.PrimvarsAPI(prim).GetPrimvar(uv_set).HasAuthoredValue()
        assert (cases.root.parent / "grid.png").is_file()  # the texture the material names


# --- F-NESTED-STRESS ----------------------------------------------------------------------------------


def _sheared(matrix: Gf.Matrix4d) -> bool:
    rows = [Gf.Vec3d(*(matrix[r][c] for c in range(3))) for r in range(3)]
    return any(abs(Gf.Dot(rows[a], rows[b])) > 1e-9 for a, b in ((0, 1), (0, 2), (1, 2)))


def test_stress_world_transforms(stress: StressScene) -> None:
    drawn = {str(p.GetPath()): p for p in _meshes(stress.stage, "/World")}
    assert set(stress.world) == set(drawn)
    cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    for path, expected in stress.world.items():
        world = cache.GetLocalToWorldTransform(drawn[path])
        assert Gf.IsClose(world, expected, 1e-9), path
        assert (world.GetDeterminant() < 0) == (path in stress.negative), path
        assert _sheared(world) == (path in stress.sheared), path


def test_stress_purposes(stress: StressScene) -> None:
    for path in stress.world:
        imageable = UsdGeom.Imageable(stress.stage.GetPrimAtPath(path))
        visible = imageable.ComputeVisibility() == UsdGeom.Tokens.inherited
        purpose = imageable.ComputePurpose()
        assert (visible and purpose in (UsdGeom.Tokens.default_, UsdGeom.Tokens.proxy)) == (path in stress.viewport)
        assert (visible and purpose in (UsdGeom.Tokens.default_, UsdGeom.Tokens.render)) == (path in stress.render)


def test_stress_display_color(stress: StressScene) -> None:
    for path, expected in stress.display_color.items():
        primvar = _inherited(stress.stage.GetPrimAtPath(path), "displayColor")
        if expected is None:
            assert primvar is None, path
        else:
            assert primvar is not None, path
            assert tuple(primvar.ComputeFlattened()[0]) == pytest.approx(expected), path


def test_stress_copies_of_a_mesh_differ_in_appearance(stress: StressScene) -> None:
    # Nested instances with differing appearance: one prototype mesh shows more than one display color.
    leaves = [p for p in stress.display_color if p.endswith("/Inner/Geom")]
    assert len({stress.display_color[p] for p in leaves}) == len(leaves)
