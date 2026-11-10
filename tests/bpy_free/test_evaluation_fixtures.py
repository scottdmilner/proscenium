"""The evaluation fixture generators produce the scenes their docstrings claim, by USD's own APIs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Kind, Tf, Usd, UsdGeom

from fixtures import evaluation
from fixtures.evaluation import LOAD, RENDER_PURPOSES, UNIT_SCALES, VIEWPORT_PURPOSES
from proscenium.binding.source_access.stages import PayloadPolicy
from support.usd import open_stage_without_cache

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

MESH, BOUNDABLE = Tf.Type.Find(UsdGeom.Mesh), Tf.Type.Find(UsdGeom.Boundable)
POINT_INSTANCER, GPRIM = Tf.Type.Find(UsdGeom.PointInstancer), Tf.Type.Find(UsdGeom.Gprim)


def _time(time_code: float | None) -> Usd.TimeCode:
    return Usd.TimeCode.Default() if time_code is None else Usd.TimeCode(time_code)


def _close(a: Gf.Matrix4d, b: Gf.Matrix4d) -> bool:
    return all(Gf.IsClose(a[i][j], b[i][j], 1e-9) for i in range(4) for j in range(4))


def _world(stage: Usd.Stage, path: str, time_code: float | None = None) -> Gf.Matrix4d:
    return UsdGeom.XformCache(_time(time_code)).GetLocalToWorldTransform(stage.GetPrimAtPath(path))


def _drawn(stage: Usd.Stage, schema: Tf.Type = MESH) -> set[str]:
    """Every prim of the schema, instance proxies included, outside abstract (class) prims."""
    return {
        str(prim.GetPath())
        for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())
        if prim.IsA(schema)
    }


def _sheared(matrix: Gf.Matrix4d) -> bool:
    rows = [matrix.GetRow3(i) for i in range(3)]
    return any(abs(Gf.Dot(rows[i], rows[j])) > 1e-9 for i in range(3) for j in range(i + 1, 3))


# --- F-TRANSFORMS --------------------------------------------------------------------------------------------


@pytest.fixture
def transforms(tmp_path: Path) -> Iterator[evaluation.TransformsScene]:
    with evaluation.transforms(tmp_path) as scene:
        yield scene


@pytest.mark.parametrize("policy", list(PayloadPolicy))
def test_transforms_drawn_meshes(policy: PayloadPolicy, transforms: evaluation.TransformsScene) -> None:
    stage = open_stage_without_cache(transforms.root, LOAD[policy])
    assert _drawn(stage) == transforms.drawn(policy)


def test_transforms_world_transforms(transforms: evaluation.TransformsScene) -> None:
    for path, expected in transforms.world.items():
        time_code = 0.0 if path == evaluation.ANIMATED else None
        assert _close(_world(transforms.stage, path, time_code), expected), path


def test_transforms_determinants_and_shear(transforms: evaluation.TransformsScene) -> None:
    for path in transforms.world:
        matrix = _world(transforms.stage, path, 0.0)
        assert (matrix.GetDeterminant() < 0) == (path in transforms.negative), path
        assert _sheared(matrix) == (path in transforms.sheared), path


def test_transforms_resets(transforms: evaluation.TransformsScene) -> None:
    for path in transforms.world:
        prim = transforms.stage.GetPrimAtPath(path)
        assert UsdGeom.Xformable(prim).GetResetXformStack() == (path in transforms.resets), path


def test_transforms_instance_context(transforms: evaluation.TransformsScene) -> None:
    for path in transforms.world:
        prim = transforms.stage.GetPrimAtPath(path)
        roots, ancestor = [], prim.GetParent()
        while ancestor and not ancestor.IsPseudoRoot():
            if ancestor.IsInstance():
                roots.insert(0, str(ancestor.GetPath()))
            ancestor = ancestor.GetParent()
        assert tuple(roots) == transforms.instance_context.get(path, ()), path


def test_transforms_bounds(transforms: evaluation.TransformsScene) -> None:
    for path in transforms.world:
        extent = UsdGeom.Mesh(transforms.stage.GetPrimAtPath(path)).GetExtentAttr().Get()
        assert (Gf.Vec3d(extent[0]), Gf.Vec3d(extent[1])) == evaluation.UNIT_BOUNDS, path


@pytest.mark.parametrize("time_code", [None, -5.0, 0.0, 5.0, 10.0, 12.5, 17.25, 20.0, 25.0, 30.0, 35.0])
def test_transforms_animated(time_code: float | None, transforms: evaluation.TransformsScene) -> None:
    matrix = transforms.world_at(evaluation.ANIMATED, time_code)
    assert _close(_world(transforms.stage, evaluation.ANIMATED, time_code), matrix)


def test_transforms_equal_time_codes_and_samples(transforms: evaluation.TransformsScene) -> None:
    attr = transforms.stage.GetPrimAtPath("/World/Animated").GetAttribute("xformOp:translate")
    assert tuple(attr.GetTimeSamples()) == transforms.variation.samples
    assert (transforms.stage.GetStartTimeCode(), transforms.stage.GetEndTimeCode()) == (
        transforms.variation.start,
        transforms.variation.end,
    )
    for first, second in transforms.equal_time_codes:
        assert _world(transforms.stage, evaluation.ANIMATED, first) == _world(
            transforms.stage, evaluation.ANIMATED, second
        )


def test_transforms_projective(transforms: evaluation.TransformsScene) -> None:
    matrix = _world(transforms.projective_stage, transforms.projective)
    assert _close(matrix, transforms.projective_world)
    assert matrix.GetColumn(3) != Gf.Vec4d(0, 0, 0, 1)  # projective, so no object can hold it
    affine = Gf.Matrix4d(matrix)
    affine.SetColumn(3, Gf.Vec4d(0, 0, 0, 1))
    assert _close(affine, transforms.projective_affine)
    stage = transforms.projective_stage
    assert _drawn(stage) == {transforms.projective, *transforms.projective_instanced}
    for path, expected in transforms.projective_instanced.items():
        assert stage.GetPrimAtPath(path).IsInstanceProxy(), path
        world = _world(stage, path)
        assert world.GetColumn(3) != Gf.Vec4d(0, 0, 0, 1), path
        world.SetColumn(3, Gf.Vec4d(0, 0, 0, 1))
        assert _close(world, expected), path
    assert transforms.projective_reported == tuple(
        sorted((transforms.projective, min(transforms.projective_instanced)))
    )


# --- F-UNITS-UP-AXIS -----------------------------------------------------------------------------------------


@pytest.fixture
def units(tmp_path: Path) -> Iterator[evaluation.UnitsScene]:
    with evaluation.units_up_axis(tmp_path) as scene:
        yield scene


def test_units_metadata_and_content(units: evaluation.UnitsScene) -> None:
    for key, stage in units.stages.items():
        assert UsdGeom.GetStageMetersPerUnit(stage) == units.meters_per_unit[key]
        assert UsdGeom.GetStageUpAxis(stage) == units.up_axis[key]
        assert _drawn(stage) == set(units.world)
        for path, expected in units.world.items():
            assert _close(_world(stage, path), expected), (key, path)
            extent = UsdGeom.Mesh(stage.GetPrimAtPath(path)).GetExtentAttr().Get()
            assert (Gf.Vec3d(extent[0]), Gf.Vec3d(extent[1])) == units.bounds, (key, path)
            assert stage.GetPrimAtPath(path).IsInstanceProxy() == (path in units.instance_context), (key, path)


@pytest.mark.parametrize("scale_length", UNIT_SCALES)
def test_units_correction(scale_length: float, units: evaluation.UnitsScene) -> None:
    # Z-up in meters into a scene of scale 1 needs no correction; Y-up turns +Y into +Z.
    z_up = units.correction("z-up-m", scale_length)
    assert _close(z_up, evaluation.scale(1 / scale_length, 1 / scale_length, 1 / scale_length))
    y_up = units.correction("y-up-cm", scale_length)
    factor = 0.01 / scale_length
    assert Gf.IsClose(y_up.TransformDir(Gf.Vec3d(0, 1, 0)), Gf.Vec3d(0, 0, factor), 1e-12)
    assert Gf.IsClose(y_up.TransformDir(Gf.Vec3d(1, 0, 0)), Gf.Vec3d(factor, 0, 0), 1e-12)


# --- F-VISIBILITY-PURPOSE ------------------------------------------------------------------------------------


@pytest.fixture
def visibility(tmp_path: Path) -> Iterator[evaluation.VisibilityScene]:
    with evaluation.visibility_purpose(tmp_path) as scene:
        yield scene


def test_visibility_purposes(visibility: evaluation.VisibilityScene) -> None:
    assert _drawn(visibility.stage) == set(visibility.purpose)
    for path, purpose in visibility.purpose.items():
        assert UsdGeom.Imageable(visibility.stage.GetPrimAtPath(path)).ComputePurpose() == purpose, path


@pytest.mark.parametrize("time_code", [None, 0.0, 5.0, 10.0, 15.0, 19.5, 20.0, 25.0])
def test_visibility_over_time(time_code: float | None, visibility: evaluation.VisibilityScene) -> None:
    for path, purpose in visibility.purpose.items():
        imageable = UsdGeom.Imageable(visibility.stage.GetPrimAtPath(path))
        if purpose == "guide":  # no guideVisibility authored, so a guide is invisible
            assert imageable.ComputeEffectiveVisibility(UsdGeom.Tokens.guide, _time(time_code)) == "invisible"
            continue
        visible = imageable.ComputeVisibility(_time(time_code)) != UsdGeom.Tokens.invisible
        assert visible == visibility.visible(path, time_code), (path, time_code)


def test_visibility_participation_by_default(visibility: evaluation.VisibilityScene) -> None:
    viewport = {p for p in visibility.purpose if visibility.displays(p, 0.0, VIEWPORT_PURPOSES)}
    render = {p for p in visibility.purpose if visibility.displays(p, 0.0, RENDER_PURPOSES)}
    assert viewport == {"/World/Shown/Default", "/World/Shown/Proxy", "/World/ProxyGroup/Inherits"} | {
        "/World/Pair/ProxyGeo",
        evaluation.BLINKING,
    }
    assert render == {"/World/Shown/Default", "/World/Shown/Render", "/World/Pair/RenderGeo", evaluation.BLINKING}


def test_visibility_samples(visibility: evaluation.VisibilityScene) -> None:
    attr = UsdGeom.Imageable(visibility.stage.GetPrimAtPath(visibility.blinking)).GetVisibilityAttr()
    assert tuple(attr.GetTimeSamples()) == visibility.variation.samples
    for first, second in visibility.equal_time_codes:
        assert attr.Get(Usd.TimeCode(first)) == attr.Get(Usd.TimeCode(second))


# --- F-UNSUPPORTED-CONTENT -----------------------------------------------------------------------------------


@pytest.fixture
def unsupported(tmp_path: Path) -> Iterator[evaluation.UnsupportedScene]:
    with evaluation.unsupported_content(tmp_path) as scene:
        yield scene


def test_unsupported_inventory(unsupported: evaluation.UnsupportedScene) -> None:
    drawn = _drawn(unsupported.stage, BOUNDABLE)  # gprims and the volume
    expected = set(unsupported.placeholders) | unsupported.exact_conversions | unsupported.approximated
    assert drawn == expected | set(unsupported.supported_beneath)


def test_unsupported_placeholders(unsupported: evaluation.UnsupportedScene) -> None:
    for path, placeholder in unsupported.placeholders.items():
        prim = unsupported.stage.GetPrimAtPath(path)
        assert prim.GetTypeName() == placeholder.type_name, path
        assert _close(_world(unsupported.stage, path), placeholder.world), path
        imageable = UsdGeom.Imageable(prim)
        visible = imageable.ComputeVisibility() != UsdGeom.Tokens.invisible
        purpose = imageable.ComputePurpose()
        assert (visible and purpose in VIEWPORT_PURPOSES) == placeholder.viewport, path
        assert (visible and purpose in RENDER_PURPOSES) == placeholder.render, path
        authored = UsdGeom.Boundable(prim).GetExtentAttr().Get() if prim.IsA(BOUNDABLE) else None
        if placeholder.bounds is None:  # a marker: no extent authored, and none computed for its type
            assert authored is None, path
            continue
        extent = UsdGeom.Boundable.ComputeExtentFromPlugins(UsdGeom.Boundable(prim), Usd.TimeCode.Default())
        if placeholder.computed:
            assert authored is None, path
        else:
            extent = authored
        assert extent is not None, path
        assert Gf.IsClose(Gf.Vec3d(extent[0]), placeholder.bounds[0], 1e-6), path
        assert Gf.IsClose(Gf.Vec3d(extent[1]), placeholder.bounds[1], 1e-6), path


def test_unsupported_authored_extent_differs_from_computed(unsupported: evaluation.UnsupportedScene) -> None:
    # Boxed's placeholder shows its authored extent as given, which its points don't fill.
    prim = UsdGeom.Boundable(unsupported.stage.GetPrimAtPath("/World/Boxed"))
    assert prim.GetExtentAttr().Get() != UsdGeom.Boundable.ComputeExtentFromPlugins(prim, Usd.TimeCode.Default())


def test_unsupported_conversions(unsupported: evaluation.UnsupportedScene) -> None:
    types = {path: unsupported.stage.GetPrimAtPath(path).GetTypeName() for path in unsupported.approximated}
    assert types == {"/World/Shapes/Ball": "Sphere", "/World/Shapes/Sheet": "NurbsPatch"}
    assert {unsupported.stage.GetPrimAtPath(p).GetTypeName() for p in unsupported.exact_conversions} == {"Cube"}


def test_unsupported_ancestor_state(unsupported: evaluation.UnsupportedScene) -> None:
    for path, (expected, purpose) in unsupported.supported_beneath.items():
        prim = unsupported.stage.GetPrimAtPath(path)
        assert prim.IsA(MESH) and not prim.GetParent().IsA(MESH), path
        assert _close(_world(unsupported.stage, path), expected), path
        assert UsdGeom.Imageable(prim).ComputePurpose() == purpose, path


def test_unsupported_kinds(unsupported: evaluation.UnsupportedScene) -> None:
    for path, kind in unsupported.kinds.items():
        assert Usd.ModelAPI(unsupported.stage.GetPrimAtPath(path)).GetKind() == kind
        assert Kind.Registry.IsA(kind, Kind.Tokens.model)


# --- F-POINT-INSTANCERS --------------------------------------------------------------------------------------


@pytest.fixture
def points(tmp_path: Path) -> Iterator[evaluation.PointInstancerScene]:
    with evaluation.point_instancers(tmp_path) as scene:
        yield scene


def _point_copies(stage: Usd.Stage) -> dict[str, dict[str, object]]:
    """Each point instancer's copies by point-instance path, as UsdGeom composes them, with what names each."""
    cache = UsdGeom.XformCache()
    found: dict[str, dict[str, object]] = {}
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        if not prim.IsA(POINT_INSTANCER):
            continue
        instancer = UsdGeom.PointInstancer(prim)
        code = Usd.TimeCode(0.0)
        # Each prototype root's own transform included, and every point, the mask's hidden ones too.
        include, ignore = UsdGeom.PointInstancer.IncludeProtoXform, UsdGeom.PointInstancer.IgnoreMask
        frames = instancer.ComputeInstanceTransformsAtTime(code, code, include, ignore)
        mask = instancer.ComputeMaskAtTime(code) or [True] * len(frames)
        ids = instancer.GetIdsAttr().Get(code)
        roots = instancer.GetPrototypesRel().GetForwardedTargets()
        heat = UsdGeom.PrimvarsAPI(prim).GetPrimvar("heat")
        group = UsdGeom.PrimvarsAPI(prim).GetPrimvar("groupId")
        native = tuple(str(a.GetPath()) for a in reversed(list(_ancestors(prim))) if a.IsInstance())
        instancer_world = cache.GetLocalToWorldTransform(prim)
        for index, proto in enumerate(instancer.GetProtoIndicesAttr().Get(code)):
            point_id = index if ids is None else ids[index]
            name = f"__index_{index}" if ids is None else f"__id_{'n' if point_id < 0 else ''}{abs(point_id)}"
            point = f"{prim.GetPath()}/{name}"
            root = stage.GetPrimAtPath(roots[proto])
            for mesh in Usd.PrimRange(root, Usd.TraverseInstanceProxies()):
                if not mesh.IsA(MESH):
                    continue
                below = mesh.GetPath().MakeRelativePath(root.GetPath().GetParentPath())
                path = f"{point}/{below}"
                inside = mesh.GetPath() if mesh != root else None
                relative = Gf.Matrix4d(1) if inside is None else cache.ComputeRelativeTransform(mesh, root)[0]
                nested = tuple(
                    f"{point}/{a.GetPath().MakeRelativePath(root.GetPath().GetParentPath())}"
                    for a in reversed(list(_ancestors(mesh, root)))
                    if a.IsInstance()
                )
                found[path] = {
                    "world": relative * frames[index] * instancer_world,
                    "source": str(mesh.GetPath()),
                    "context": (*native, str(prim.GetPath()), point, *nested),
                    "floor": native[0] if native else str(prim.GetPath()),
                    "visible": bool(mask[index]),
                    "primvars": {
                        **({"heat": heat.Get(code)[index]} if heat else {}),
                        **({"groupId": group.Get(code)} if group else {}),
                    },
                }
    return found


def _ancestors(prim: Usd.Prim, stop: Usd.Prim | None = None) -> Iterator[Usd.Prim]:
    """Prim's ancestors, innermost first, up to but excluding the pseudo-root, or stop's parent when given."""
    parent = prim.GetParent()
    end = stop.GetParent() if stop is not None else None
    while parent and not parent.IsPseudoRoot() and parent != end:
        yield parent
        parent = parent.GetParent()


def test_point_instancer_copies(points: evaluation.PointInstancerScene) -> None:
    found = _point_copies(points.stage)
    assert found.keys() == points.world.keys()
    for path, usd in found.items():
        assert _close(usd["world"], points.world[path]), path  # ty: ignore[invalid-argument-type]
        assert usd["source"] == points.sources[path], path
        assert usd["context"] == points.instance_context[path], path
        assert usd["floor"] == points.floors[path], path
        assert usd["visible"] == (path not in points.invisible), path
        if path in points.primvars:
            assert usd["primvars"] == pytest.approx(points.primvars[path]), path
    assert {p for p, usd in found.items() if usd["primvars"]} == points.primvars.keys()


def test_point_instancer_prototypes_are_drawn_only_as_copies(points: evaluation.PointInstancerScene) -> None:
    under = {
        str(prim.GetPath())
        for prim in Usd.PrimRange(points.stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())
        if prim.IsA(GPRIM) and any(a.IsA(POINT_INSTANCER) for a in _ancestors(prim))
    }
    assert under == points.prototypes


# --- Generated transform hierarchies -------------------------------------------------------------------------


@pytest.mark.parametrize("seed", evaluation.GENERATED_SEEDS)
def test_generated_hierarchy(seed: int, tmp_path: Path) -> None:
    with evaluation.generated_hierarchy(tmp_path, seed) as scene:
        stage = scene.stage
        assert (UsdGeom.GetStageMetersPerUnit(stage), UsdGeom.GetStageUpAxis(stage)) == (
            scene.meters_per_unit,
            scene.up_axis,
        )
        assert _drawn(stage) == set(scene.world)
        for path, expected in scene.world.items():
            assert _close(_world(stage, path), expected), path
        resetting = {str(p.GetPath()) for p in stage.Traverse() if UsdGeom.Xformable(p).GetResetXformStack()}
        assert resetting == scene.resets


def test_generated_hierarchies_cover_resets_and_shears(tmp_path: Path) -> None:
    # Across the recorded seeds, so the relations run on them see both.
    resets = shears = 0
    for seed in evaluation.GENERATED_SEEDS:
        with evaluation.generated_hierarchy(tmp_path / str(seed), seed) as scene:
            resets += len(scene.resets)
            shears += sum(_sheared(w) for w in scene.world.values())
    assert resets and shears


def test_one_seed_writes_the_same_layer(tmp_path: Path) -> None:
    # TMETA-04: byte for byte; another seed writes another.
    written = []
    for name, seed in (("one", 17), ("again", 17), ("other", 29)):
        with evaluation.generated_hierarchy(tmp_path / name, seed) as scene:
            written.append(scene.root.read_bytes())
    assert written[0] == written[1] != written[2]
