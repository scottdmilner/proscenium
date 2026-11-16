"""F-TIME-VARIATIONS displays what its generator says at every sampled time code, by USD's own APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Tf, Usd, UsdGeom

from fixtures import time_variations
from support.time_codes import sampled

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fixtures.edit_sequence import CopyIdentity

MESH, GPRIM = Tf.Type.Find(UsdGeom.Mesh), Tf.Type.Find(UsdGeom.Gprim)
INSTANCER = Tf.Type.Find(UsdGeom.PointInstancer)
Aspect = time_variations.VaryingAspect


@pytest.fixture
def scene(tmp_path: Path) -> Iterator[time_variations.TimeVariationsScene]:
    with time_variations.time_variations(tmp_path) as scene:
        yield scene


def _usd_time(time_code: float | None) -> Usd.TimeCode:
    return Usd.TimeCode.Default() if time_code is None else Usd.TimeCode(time_code)


def _sheared(matrix: Gf.Matrix4d) -> bool:
    rows = [matrix.GetRow3(i) for i in range(3)]
    return any(abs(Gf.Dot(rows[i], rows[j])) > 1e-9 for i in range(3) for j in range(i + 1, 3))


@dataclass(frozen=True)
class CopyState:
    """A drawn copy at one time code, by USD."""

    world_matrix: Gf.Matrix4d
    visible: bool
    extent: tuple[Gf.Vec3f, ...] | None  # a placeholder's authored bounds; None for a mesh, a point, or a marker


def _evaluated(stage: Usd.Stage, time_code: float | None) -> dict[CopyIdentity, CopyState]:
    """Each copy drawn at the time code, by USD."""
    time, cache, drawn = _usd_time(time_code), UsdGeom.XformCache(_usd_time(time_code)), {}
    prims = iter(Usd.PrimRange(stage.GetPseudoRoot()))
    for prim in prims:
        if prim.IsA(INSTANCER):
            prims.PruneChildren()
            instancer = UsdGeom.PointInstancer(prim)
            targets = instancer.GetPrototypesRel().GetTargets()
            transforms = instancer.ComputeInstanceTransformsAtTime(time, time)
            for index, proto_index in enumerate(instancer.GetProtoIndicesAttr().Get(time)):
                point = f"{prim.GetPath()}/__index_{index}"
                identity = (f"{point}/{targets[proto_index].name}", (str(prim.GetPath()), point))
                drawn[identity] = CopyState(transforms[index], True, None)
        elif prim.IsA(GPRIM):
            extent = None if prim.IsA(MESH) else UsdGeom.Boundable(prim).GetExtentAttr().Get(time)
            visible = UsdGeom.Imageable(prim).ComputeVisibility(time) != UsdGeom.Tokens.invisible
            world = cache.GetLocalToWorldTransform(prim)
            drawn[(str(prim.GetPath()), ())] = CopyState(world, visible, None if extent is None else tuple(extent))
    return drawn


def _time_codes(scene: time_variations.TimeVariationsScene) -> tuple[float | None, ...]:
    return sampled("F-TIME-VARIATIONS", scene.variation).time_codes


def test_copies_shear_and_boxes(scene: time_variations.TimeVariationsScene) -> None:
    for time_code in _time_codes(scene):
        evaluated = _evaluated(scene.stage, time_code)
        assert set(evaluated) == scene.copies(time_code), time_code
        sheared = {identity for identity, state in evaluated.items() if _sheared(state.world_matrix)}
        assert sheared == scene.sheared(time_code), time_code
        placeholders = {  # a point's copy has no prim of its own, and every prototype here is a mesh
            identity
            for identity in evaluated
            if not identity[1] and not scene.stage.GetPrimAtPath(identity[0]).IsA(MESH)
        }
        boxes = {identity for identity in placeholders if evaluated[identity].extent is not None}
        assert boxes == scene.boxes(time_code), time_code
        assert evaluated[(time_variations.BLINK, ())].visible == scene.blink_visible(time_code), time_code


def test_varying_aspects(scene: time_variations.TimeVariationsScene) -> None:
    by_time = {time_code: _evaluated(scene.stage, time_code) for time_code in _time_codes(scene)}
    assert set(scene.varying) == {identity for evaluated in by_time.values() for identity in evaluated}
    for identity, aspects in scene.varying.items():
        present = [evaluated[identity] for evaluated in by_time.values() if identity in evaluated]
        assert (len(present) < len(by_time)) == (Aspect.EXISTENCE in aspects), identity
        matrices = {state.world_matrix for state in present}
        assert (len(matrices) > 1) == (Aspect.TRANSFORM in aspects), identity
        assert (len({state.visible for state in present}) > 1) == (Aspect.VISIBILITY in aspects), identity
        shears = {identity in scene.sheared(time_code) for time_code in by_time if identity in by_time[time_code]}
        assert (len(shears) > 1) == (Aspect.SHEAR in aspects), identity
        extents = [state.extent for state in present]
        presence = {extent is None for extent in extents}
        assert (len(presence) > 1) == (Aspect.BOUNDS_PRESENCE in aspects), identity
        values = {extent for extent in extents if extent is not None}
        assert (len(values) > 1) == (Aspect.BOUNDS in aspects), identity


def test_cache_groupings(scene: time_variations.TimeVariationsScene) -> None:
    first, *others = scene.cache_groupings
    expected = sorted(time_code for call in first for time_code in call)
    assert scene.synchronized not in expected
    assert any(time_code != int(time_code) for time_code in expected)  # a subframe (XFORM-11)
    for grouping in others:
        assert sorted(time_code for call in grouping for time_code in call) == expected
        assert grouping != first
