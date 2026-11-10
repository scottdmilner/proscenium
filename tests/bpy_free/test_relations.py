"""Metamorphic relations 1, 4, 5, and 6 on the bespoke fixtures, and 1 and 2 on generated inputs (M6 plan, A3).

Each compares the plans of two inputs, captured and planned here under the default settings and context, conversion
off unless relation 2 turns it on. Relation 2 on F-UNITS-UP-AXIS and relation 3 are test_core_conversion.py's and
test_core_visibility.py's. Generated hierarchies come from the seeds evaluation.GENERATED_SEEDS records, each a test
parameter (TMETA-04). Every fixture and generated input these run on has tests of its own expected values too
(TMETA-01): test_evaluation_fixtures.py's and the fixtures' cases.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Usd, UsdGeom

from fixtures import appearance, evaluation
from proscenium.binding.source_access import stages
from proscenium.binding.source_access.stages import PayloadPolicy
from proscenium.core import _core

from .plan_checks import SETTINGS, PlannedDrawnCopy, assert_world, copies, plan_at
from .plan_process import contents

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

SHIFT = Gf.Vec3d(3.0, -2.0, 5.0)  # relation 1's translation
CONVERTING = _core.PlanSettings(evaluation.VIEWPORT_PURPOSES, evaluation.RENDER_PURPOSES, coordinate_conversion=True)


@pytest.fixture
def transforms(tmp_path: Path) -> Iterator[evaluation.TransformsScene]:
    with evaluation.transforms(tmp_path) as scene:
        yield scene


@pytest.fixture
def stress(tmp_path: Path) -> Iterator[appearance.StressScene]:
    with appearance.nested_stress(tmp_path) as scene:
        yield scene


def _unmoved(copy: PlannedDrawnCopy) -> tuple[object, ...]:
    """What relation 1 leaves alone: all but the world transform and a shear split, which follows it."""
    return (
        copy.local_bounds,
        copy.visible_in_viewport,
        copy.visible_in_render,
        copy.geometry_index,
        copy.placeholder_bounds_index,
        copy.shear_transform_split is None,
    )


def _resets(stage: Usd.Stage, path: str) -> bool:
    """Whether the prim at path, or an ancestor of it, resets the transform stack, from UsdGeom."""
    prim = stage.GetPrimAtPath(path)
    while prim and not prim.IsPseudoRoot():
        if (xformable := UsdGeom.Xformable(prim)) and xformable.GetResetXformStack():
            return True
        prim = prim.GetParent()
    return False


def _diagnostics(plan: _core.Plan) -> list[object]:
    return contents(plan)["diagnostics"]


def _check_root_translation(stage: Usd.Stage) -> set[str]:
    """Relation 1 on stage, as test_relation_1_root_translation states it; the copies that stay put."""
    before = plan_at(stage, 0.0)
    world = UsdGeom.Xformable(stage.GetPrimAtPath("/World"))
    order = world.GetOrderedXformOps()
    shift = world.AddTranslateOp(opSuffix="relation1")
    shift.Set(SHIFT)
    world.SetXformOpOrder([shift, *order])
    after = plan_at(stage, 0.0)
    moved, shown = copies(before), copies(after)
    assert shown.keys() == moved.keys()
    pinned = {path for path in shown if _resets(stage, path)}
    for path, copy in shown.items():
        translation = Gf.Matrix4d(1) if path in pinned else Gf.Matrix4d().SetTranslate(SHIFT)
        assert_world(copy, moved[path].world_matrix * translation)
        assert _unmoved(copy) == _unmoved(moved[path]), path
    assert contents(after)["correspondence"] == contents(before)["correspondence"]
    assert _diagnostics(after) == _diagnostics(before)
    return pinned


@pytest.mark.parametrize("fixture", ["transforms", "stress"])
def test_relation_1_root_translation(fixture: str, request: pytest.FixtureRequest) -> None:
    """Relation 1, root translation (XFORM-01, XFORM-02).

    Input: a translate op of t put first in World's xformOpOrder, so it applies after World's own ops. Effect: each
    drawn copy's world transform W becomes W · T(t), in USD's row-vector convention, but for a copy beneath a reset
    transform stack, which doesn't move; sources, instance contexts, participation, local bounds, and diagnostics are
    unchanged. On F-TRANSFORMS "root-translation" and F-NESTED-STRESS "root-translation", whose Pinned copies stay put.
    """
    scene = request.getfixturevalue(fixture)
    pinned = _check_root_translation(scene.stage)
    assert pinned  # so the fixed copies are checked
    if fixture == "transforms":
        assert scene.reset_transform_paths < pinned  # and Socket/Geom, below a nested instance root that resets it


@pytest.mark.parametrize("seed", evaluation.GENERATED_SEEDS)
def test_relation_1_on_generated_hierarchies(seed: int, tmp_path: Path) -> None:
    """Relation 1, root translation (XFORM-01, XFORM-02), on a hierarchy generated from seed (TMETA-04).

    Input and effect as test_relation_1_root_translation states them, on random translate, rotate, and scale ops,
    negative and nonuniform scales, and resets of the transform stack (evaluation.generated_hierarchy).
    """
    with evaluation.generated_hierarchy(tmp_path, seed) as scene:
        pinned = _check_root_translation(scene.stage)
        assert pinned == {
            p
            for p in scene.world_matrices_by_source
            if any(p == r or p.startswith(f"{r}/") for r in scene.reset_transform_paths)
        }


@pytest.mark.parametrize("scale_length", evaluation.UNIT_SCALES)
@pytest.mark.parametrize("seed", evaluation.GENERATED_SEEDS)
def test_relation_2_on_generated_hierarchies(seed: int, scale_length: float, tmp_path: Path) -> None:
    """Relation 2, conversion (CONV-01, CONV-03, CONV-08), on a hierarchy generated from seed (TMETA-04).

    Input: coordinate_conversion turned on, planning one snapshot under both settings. Effect: each drawn copy's
    world transform W, its objects' product for a sheared copy, becomes W · C, C the spec's correction for the stage's
    metersPerUnit and upAxis and the target scene's unit scale (evaluation.correction); local bounds, sources,
    participation, and diagnostics are unchanged. Relation 2 on F-UNITS-UP-AXIS is test_core_conversion.py's.
    """
    with evaluation.generated_hierarchy(tmp_path, seed) as scene:
        chain = _core.SceneIndexChain(scene.stage)
        try:
            snapshot = chain.capture(Usd.TimeCode(0.0))
        finally:
            chain.release()
        context = _core.PlanningContext(scale_length, 1)
        off = _core.plan(snapshot, SETTINGS, context)
        on = _core.plan(snapshot, CONVERTING, context)
        correction = evaluation.correction(scene.meters_per_unit, scene.up_axis, scale_length)
        plain, converted = copies(off), copies(on)
        assert converted.keys() == plain.keys() == scene.world_matrices_by_source.keys()
        for path, copy in converted.items():
            assert_world(copy, scene.world_matrices_by_source[path] * correction)
            if copy.shear_transform_split is not None:  # the object below its shear parent
                parent, basis = copy.shear_transform_split
                assert_world(
                    dataclasses.replace(copy, world_matrix=basis * parent),
                    scene.world_matrices_by_source[path] * correction,
                )
            assert_world(plain[path], scene.world_matrices_by_source[path])
            assert (copy.local_bounds, copy.visible_in_viewport, copy.visible_in_render) == (
                plain[path].local_bounds,
                plain[path].visible_in_viewport,
                plain[path].visible_in_render,
            ), path
        assert contents(on)["correspondence"] == contents(off)["correspondence"]
        assert _diagnostics(on) == _diagnostics(off)


def test_relation_4_payload_round_trip(transforms: evaluation.TransformsScene) -> None:
    """Relation 4, payload round trip (BIND-04, ASTD-01; PLAN-08).

    Input: a binding's evaluation stage acquired under load-all, then load-none, then load-all again, captured each
    time. Effect: the plan after switching back equals the one before in every part and its order; the one between
    lacks the payload's meshes. On F-TRANSFORMS "payload-round-trip".
    """
    binding_stages = stages.BindingStages()
    binding_stages.attach(transforms.stage)
    try:
        first = contents(plan_at(binding_stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL), 0.0))
        unloaded = plan_at(binding_stages.acquire_evaluation_stage(PayloadPolicy.LOAD_NONE), 0.0)
        assert copies(unloaded).keys() == transforms.drawn(PayloadPolicy.LOAD_NONE)
        assert contents(plan_at(binding_stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL), 0.0)) == first
    finally:
        binding_stages.release()


@pytest.mark.parametrize("fixture", ["transforms", "visibility"])
def test_relation_5_equal_values_at_another_time_code(fixture: str, tmp_path: Path) -> None:
    """Relation 5, equal values at another time code (XFORM-06, PLAN-08).

    Input: captures at two time codes where the fixture is built to give equal values: before the first authored
    sample and at it, after the last and at it, and two between equal samples. Effect: the plans are equal in every
    part and its order but for their time codes. On F-TRANSFORMS "equal-values" and F-VISIBILITY-PURPOSE
    "time-varying".
    """
    build = evaluation.transforms if fixture == "transforms" else evaluation.visibility_purpose
    with build(tmp_path) as scene:
        assert scene.equal_time_codes
        for first, second in scene.equal_time_codes:
            one, other = plan_at(scene.stage, first), plan_at(scene.stage, second)
            assert (one.time_code.GetValue(), other.time_code.GetValue()) == (first, second)
            assert contents(one) == contents(other), (first, second)


def test_relation_6_instanceable(stress: appearance.StressScene) -> None:
    """Relation 6, instanceable (ARCH-05's premise, checked on M6's plan).

    Input: instanceable turned off on every instance root, nested ones included. Effect: the same drawn copies, each
    keeping its source path, world transform, participation, and bounds; only instance contexts, now empty, and
    provisional sharing differ, geometry descriptions and so batch groups. On F-NESTED-STRESS "instanceable".
    """
    stage = stress.stage
    before = plan_at(stage, 0.0)
    assert any(c.instance_context for c in before.correspondence)  # so the contexts are checked
    # Turning off an outer root makes the roots inside it ordinary prims, which the next pass can edit.
    with Usd.EditContext(stage, stage.GetRootLayer()):
        while roots := [p for p in stage.Traverse() if p.IsInstance()]:
            for prim in roots:
                prim.SetInstanceable(False)
    after = plan_at(stage, 0.0)
    instanced, flat = copies(before), copies(after)
    assert flat.keys() == instanced.keys()
    for path, copy in flat.items():
        assert_world(copy, instanced[path].world_matrix)
        assert (copy.local_bounds, copy.visible_in_viewport, copy.visible_in_render) == (
            instanced[path].local_bounds,
            instanced[path].visible_in_viewport,
            instanced[path].visible_in_render,
        ), path
    assert all(c.instance_context == () for c in after.correspondence)
    assert len(after.geometries) > len(before.geometries)  # a mesh per prim, none shared by instancing
