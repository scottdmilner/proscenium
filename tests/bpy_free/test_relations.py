"""Metamorphic relations 1, 4, 5, and 6 on the bespoke fixtures (M6 plan, A3 and E3).

Each compares the plans of two inputs, captured and planned here under the default settings and context, conversion
off. Relations 2 and 3 are test_core_conversion.py's and test_core_visibility.py's. Every fixture these run on has
tests of its own expected values too (TMETA-01): test_evaluation_fixtures.py's and the fixtures' cases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Usd, UsdGeom

from fixtures import appearance, evaluation
from proscenium.binding.source_access import stages
from proscenium.binding.source_access.stages import PayloadPolicy

from .plan_checks import Copy, assert_world, copies, plan_at
from .plan_process import contents

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from proscenium.core import _core

SHIFT = Gf.Vec3d(3.0, -2.0, 5.0)  # relation 1's translation


@pytest.fixture
def transforms(tmp_path: Path) -> Iterator[evaluation.TransformsScene]:
    with evaluation.transforms(tmp_path) as scene:
        yield scene


@pytest.fixture
def stress(tmp_path: Path) -> Iterator[appearance.StressScene]:
    with appearance.nested_stress(tmp_path) as scene:
        yield scene


def _unmoved(copy: Copy) -> tuple[object, ...]:
    """What relation 1 leaves alone: all but the world transform and a shear split, which follows it."""
    return copy.bounds, copy.viewport, copy.render, copy.geometry, copy.placeholder, copy.shear is None


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


@pytest.mark.parametrize("fixture", ["transforms", "stress"])
def test_relation_1_root_translation(fixture: str, request: pytest.FixtureRequest) -> None:
    """Relation 1, root translation (XFORM-01, XFORM-02).

    Input: a translate op of t put first in World's xformOpOrder, so it applies after World's own ops. Effect: each
    drawn copy's world transform W becomes W · T(t), in USD's row-vector convention, but for a copy beneath a reset
    transform stack, which doesn't move; sources, instance contexts, participation, local bounds, and diagnostics are
    unchanged. On F-TRANSFORMS "root-translation" and F-NESTED-STRESS "root-translation", whose Pinned copies stay put.
    """
    scene = request.getfixturevalue(fixture)
    stage = scene.stage
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
    assert pinned  # so the fixed copies are checked
    if fixture == "transforms":
        assert scene.resets < pinned  # and Socket/Geom, below a nested instance root that resets it
    for path, copy in shown.items():
        translation = Gf.Matrix4d(1) if path in pinned else Gf.Matrix4d().SetTranslate(SHIFT)
        assert_world(copy, moved[path].world * translation)
        assert _unmoved(copy) == _unmoved(moved[path]), path
    assert contents(after)["correspondence"] == contents(before)["correspondence"]
    assert _diagnostics(after) == _diagnostics(before)


def test_relation_4_payload_round_trip(transforms: evaluation.TransformsScene) -> None:
    """Relation 4, payload round trip (BIND-04, ASTD-01; PLAN-08).

    Input: a binding's evaluation stage acquired under load-all, then load-none, then load-all again, captured each
    time. Effect: the plan after switching back equals the one before in every part and its order; the one between
    lacks the payload's meshes. On F-TRANSFORMS "payload-round-trip".
    """
    binding_stages = stages.BindingStages()
    binding_stages.attach(transforms.stage)
    try:
        first = contents(plan_at(binding_stages.acquire(PayloadPolicy.LOAD_ALL), 0.0))
        unloaded = plan_at(binding_stages.acquire(PayloadPolicy.LOAD_NONE), 0.0)
        assert copies(unloaded).keys() == transforms.drawn(PayloadPolicy.LOAD_NONE)
        assert contents(plan_at(binding_stages.acquire(PayloadPolicy.LOAD_ALL), 0.0)) == first
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
    provisional sharing differ. On F-NESTED-STRESS "instanceable".
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
        assert_world(copy, instanced[path].world)
        assert (copy.bounds, copy.viewport, copy.render) == (
            instanced[path].bounds,
            instanced[path].viewport,
            instanced[path].render,
        ), path
    assert all(c.instance_context == () for c in after.correspondence)
    assert len(after.geometries) > len(before.geometries)  # a mesh per prim, none shared by instancing
