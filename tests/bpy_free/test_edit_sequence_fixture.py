"""F-EDIT-SEQUENCE's steps change what their entries say, by USD's own APIs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Sdf, Tf, Usd, UsdGeom

from fixtures import edit_sequence
from support.usd import open_stage_without_cache

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fixtures.edit_sequence import CopyIdentity

MESH, GPRIM = Tf.Type.Find(UsdGeom.Mesh), Tf.Type.Find(UsdGeom.Gprim)
INSTANCER = Tf.Type.Find(UsdGeom.PointInstancer)
DEFAULT_PURPOSES = {UsdGeom.Tokens.default_, UsdGeom.Tokens.proxy, UsdGeom.Tokens.render}  # either destination's

# What a copy's display depends on in M7's content: its world matrix, whether it's visible, its purpose, whether
# it's a placeholder, its authored bounds, and, for a point's copy, the point's transform.
type CopyState = tuple[object, ...]


@pytest.fixture
def scene(tmp_path: Path) -> Iterator[edit_sequence.EditSequenceScene]:
    with edit_sequence.edit_sequence(tmp_path) as scene:
        yield scene


def _sheared(matrix: Gf.Matrix4d) -> bool:
    rows = [matrix.GetRow3(i) for i in range(3)]
    return any(abs(Gf.Dot(rows[i], rows[j])) > 1e-9 for i in range(3) for j in range(i + 1, 3))


def _instance_roots(prim: Usd.Prim) -> tuple[str, ...]:
    roots = []
    while (prim := prim.GetParent()) and not prim.IsPseudoRoot():
        if prim.IsInstance():
            roots.append(str(prim.GetPath()))
    return tuple(roots[::-1])


def _gprim_state(prim: Usd.Prim, cache: UsdGeom.XformCache) -> CopyState:
    imageable, world = UsdGeom.Imageable(prim), cache.GetLocalToWorldTransform(prim)
    extent = UsdGeom.Boundable(prim).GetExtentAttr().Get()
    return (
        world,
        imageable.ComputeVisibility() != UsdGeom.Tokens.invisible,
        imageable.ComputePurpose(),
        not prim.IsA(MESH),
        None if extent is None else tuple(extent),
        _sheared(world),
    )


def _point_element(instancer: UsdGeom.PointInstancer, index: int) -> str:
    ids = instancer.GetIdsAttr().Get()
    if not ids:
        return f"__index_{index}"
    point_id = ids[index]
    return f"__id_n{-point_id}" if point_id < 0 else f"__id_{point_id}"


def _drawn(stage: Usd.Stage) -> dict[CopyIdentity, CopyState]:
    """Every copy drawn under the default settings, by USD: gprims, and each point's copies of its prototype."""
    cache, drawn = UsdGeom.XformCache(), {}
    prims = iter(Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()))
    for prim in prims:
        if prim.IsA(INSTANCER):
            prims.PruneChildren()  # its prototypes are drawn only through its points
            instancer = UsdGeom.PointInstancer(prim)
            targets = instancer.GetPrototypesRel().GetTargets()
            transforms = instancer.ComputeInstanceTransformsAtTime(Usd.TimeCode.Default(), Usd.TimeCode.Default())
            for index, proto_index in enumerate(instancer.GetProtoIndicesAttr().Get()):
                point = f"{prim.GetPath()}/{_point_element(instancer, index)}"
                prototype = stage.GetPrimAtPath(targets[proto_index])
                for proto_prim in Usd.PrimRange(prototype):
                    if proto_prim.IsA(GPRIM):
                        below = proto_prim.GetPath().MakeRelativePath(prototype.GetPath().GetParentPath())
                        identity = (f"{point}/{below}", (*_instance_roots(prim), str(prim.GetPath()), point))
                        drawn[identity] = (transforms[index], *_gprim_state(proto_prim, cache))
        elif prim.IsA(GPRIM) and UsdGeom.Imageable(prim).ComputePurpose() in DEFAULT_PURPOSES:
            drawn[(str(prim.GetPath()), _instance_roots(prim))] = _gprim_state(prim, cache)
    return drawn


def test_initial_copies(scene: edit_sequence.EditSequenceScene) -> None:
    assert set(_drawn(scene.stage)) == scene.initial_copies


def test_steps(scene: edit_sequence.EditSequenceScene) -> None:
    assert len({step.name for step in scene.steps}) == len(scene.steps)
    expected = set(scene.initial_copies)
    for step in scene.steps:
        before = _drawn(scene.stage)
        existed = {path for path in step.source_affected if scene.stage.GetPrimAtPath(path)}
        step.edit(scene.stage)
        after = _drawn(scene.stage)
        assert set(before) == expected, step.name
        assert step.retired <= set(before) and not step.retired & set(after), step.name
        assert step.built <= set(after) and not step.built & set(before), step.name
        assert set(after) == set(before) - step.retired | step.built, step.name
        kept = set(before) & set(after)
        changed = {identity for identity in kept if before[identity] != after[identity]}
        assert not step.updated & step.rebuilt, step.name
        assert step.updated | step.rebuilt == changed, step.name
        # A copy whose shear or whose placeholder's bounds appear or vanish changes its resources: rebuilt.
        restructured = {
            identity
            for identity in changed
            if before[identity][-1] != after[identity][-1]
            or (after[identity][-3] and (before[identity][-2] is None) != (after[identity][-2] is None))
        }
        assert restructured <= step.rebuilt, step.name
        # Each source-affected prim is one the edit touched: there before it, or after it.
        assert all(path in existed or scene.stage.GetPrimAtPath(path) for path in step.source_affected), step.name
        expected = set(after)


def test_payloaded_copies(scene: edit_sequence.EditSequenceScene) -> None:
    unloaded = open_stage_without_cache(scene.root_layer_path, Usd.Stage.LoadNone)
    assert set(_drawn(unloaded)) == scene.initial_copies - scene.payloaded_copies


def test_guide_copies(scene: edit_sequence.EditSequenceScene) -> None:
    guides = {
        identity
        for identity in scene.guide_copies
        if UsdGeom.Imageable(scene.stage.GetPrimAtPath(identity[0])).ComputePurpose() == UsdGeom.Tokens.guide
    }
    assert guides == scene.guide_copies
    assert not scene.guide_copies & set(_drawn(scene.stage))


def test_keyed_copies(scene: edit_sequence.EditSequenceScene) -> None:
    def world(identity: CopyIdentity, time_code: float) -> Gf.Matrix4d:
        prim = scene.stage.GetPrimAtPath(identity[0])
        return UsdGeom.XformCache(Usd.TimeCode(time_code)).GetLocalToWorldTransform(prim)

    plain = {identity for identity in scene.initial_copies if not identity[1]}
    for time_code in scene.cached_time_codes:
        varying = {identity for identity in plain if world(identity, time_code) != world(identity, 0.0)}
        assert varying == scene.keyed_copies, time_code


def _far_translation(stage: Usd.Stage) -> Gf.Vec3d:
    prim = stage.GetPrimAtPath(edit_sequence.FAR)
    return UsdGeom.XformCache().GetLocalToWorldTransform(prim).ExtractTranslation()


def test_far_reloaded(scene: edit_sequence.EditSequenceScene) -> None:
    before = _drawn(scene.stage)
    assert _far_translation(scene.stage) == edit_sequence.FAR_TRANSLATION
    scene.rewrite_far_on_disk()
    assert _far_translation(scene.stage) == edit_sequence.FAR_TRANSLATION  # until reloaded
    Sdf.Layer.Find(str(scene.sub_layer_path)).Reload()
    after = _drawn(scene.stage)
    assert _far_translation(scene.stage) == edit_sequence.FAR_RELOADED
    assert {identity for identity in before if before[identity] != after[identity]} == {(edit_sequence.FAR, ())}


def test_attached_stage(scene: edit_sequence.EditSequenceScene) -> None:
    before, attached = _drawn(scene.stage), scene.open_attached_stage()
    after = _drawn(attached)
    assert _far_translation(attached) == edit_sequence.FAR_ATTACHED
    assert set(after) == set(before)
    assert {identity for identity in before if before[identity] != after[identity]} == {(edit_sequence.FAR, ())}
