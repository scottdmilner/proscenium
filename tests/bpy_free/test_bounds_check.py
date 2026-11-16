"""The Bounds Comparison Contract's check (support/bounds_check.py) on displays made by hand from the core's plans.

Each display here is what M7's application layer draws of a plan, made from the plan's own buffers: each copy's local
bounds' corners under its world matrix, shown where the plan says. The check reads the same copies' bounds and
transforms from USD instead, so agreement means the planner and USD agree under the contract's decisions (ABND-02).
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Usd

from fixtures import appearance, evaluation, interaction, production_like
from support import bounds_check
from support.bounds_check import DisplayedCopy

from .plan_checks import CONTEXT, SETTINGS, copies

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.core import _core

STRAND = "/World/Placed/Strand"  # F-UNSUPPORTED-CONTENT's placeholder inside a component, rotated, render-only


def _plan(
    stage: Usd.Stage, context: _core.PlanningContext = CONTEXT, settings: _core.PlanSettings = SETTINGS
) -> _core.Plan:
    from proscenium.core import _core

    chain = _core.SceneIndexChain(stage)
    try:
        return _core.plan(chain.capture(Usd.TimeCode(0.0)), settings, context)
    finally:
        chain.release()


def _drawn(plan: _core.Plan) -> list[DisplayedCopy]:
    """What M7 draws of the plan: each copy's local bounds' corners under its world matrix, a marker none."""
    found = []
    for source, copy in copies(plan).items():
        local = copy.local_bounds
        vertices = tuple(
            bounds_check.world_point(copy.world_matrix, c)
            for c in (bounds_check.corners(local[:3], local[3:]) if local else ())
        )
        found.append(DisplayedCopy(source, copy.visible_in_viewport, copy.visible_in_render, vertices))
    return found


def _check(stage: Usd.Stage, plan: _core.Plan, displayed: list[DisplayedCopy]) -> list[str]:
    identity = Gf.Matrix4d(1.0)
    return bounds_check.model_bounds_mismatches(
        stage, Usd.TimeCode(0.0), bounds_check.planned_copies(plan), displayed, identity
    )


def _moved(displayed: list[DisplayedCopy], source: str, dx: float) -> list[DisplayedCopy]:
    return [
        dataclasses.replace(c, world_vertices=tuple((x + dx, y, z) for x, y, z in c.world_vertices))
        if c.source_path == source
        else c
        for c in displayed
    ]


@pytest.mark.parametrize("stage", ["y-up-cm", "z-up-m"])
@pytest.mark.parametrize("scale_length", evaluation.UNIT_SCALES)
def test_the_conversion_is_the_specs(stage: str, scale_length: float, tmp_path: Path) -> None:
    # ABND-02: the check's correction is the spec's, as F-UNITS-UP-AXIS computes it by hand; off, the identity.
    with evaluation.units_up_axis(tmp_path) as scene:
        found = bounds_check.conversion_correction(scene.stages[stage], True, scale_length)
        expected = scene.correction(stage, scale_length)
        assert all(abs(found[r, c] - expected[r, c]) < 1e-12 for r in range(4) for c in range(4))
        assert bounds_check.conversion_correction(scene.stages[stage], False, scale_length) == Gf.Matrix4d(1.0)


def test_the_planned_copies_are_the_plans_decisions(tmp_path: Path) -> None:
    # ABND-02: participation comes from the plan, as F-VISIBILITY-PURPOSE builds it, never decided by the check.
    with evaluation.visibility_purpose(tmp_path) as scene:
        planned = bounds_check.planned_copies(_plan(scene.stage))
    assert {c.source_path: (c.visible_in_viewport, c.visible_in_render) for c in planned} == {
        path: (
            scene.displays(path, 0.0, evaluation.VIEWPORT_PURPOSES),
            scene.displays(path, 0.0, evaluation.RENDER_PURPOSES),
        )
        for path, purpose in scene.purpose.items()
        if purpose != "guide"
    }


@pytest.mark.parametrize(
    "fixture",
    [
        evaluation.unsupported_content,
        appearance.nested_stress,
        interaction.kind_hierarchy,
        interaction.nested_selection,
    ],
    ids=["unsupported-content", "nested-stress", "kind-hierarchy", "nested-selection"],
)
def test_what_m7_draws_of_a_plan_matches(fixture: object, tmp_path: Path) -> None:
    # ASTD-02's check on the plan's own drawing: placeholders and markers, shear and rotation inside nested
    # instances, and every model-kind prim.
    with fixture(tmp_path) as scene:  # ty: ignore[call-non-callable]
        stage = scene.stage
        plan = _plan(stage)
        assert _check(stage, plan, _drawn(plan)) == []


def test_the_check_compares_every_model_once_per_drawn_copy(tmp_path: Path) -> None:
    # ABND-03 on the production-like fixture: the models are its groups, the assembly included, and its components,
    # inside native instances too, as its parameters give them under each payload policy, and nothing else.
    for load_all in (True, False):
        root = production_like.generate(tmp_path / str(load_all))
        stage = Usd.Stage.Open(str(root), Usd.Stage.LoadAll if load_all else Usd.Stage.LoadNone)
        inventory = production_like.expected_inventory(production_like.DEFAULT, load_all)
        found = bounds_check.models(stage)
        assert len(found) == len(set(found)) == inventory["groups"] + inventory["components"]
        plan = _plan(stage)
        assert _check(stage, plan, _drawn(plan)) == []


def test_the_tolerance_accepts_within_and_fails_twice_it(tmp_path: Path) -> None:
    # ABND-09: a placeholder's box offset by half the tolerance passes; by twice it fails, for its corners and its
    # model's box.
    with evaluation.unsupported_content(tmp_path) as scene:
        stage = scene.stage
        plan = _plan(stage)
        drawn = _drawn(plan)
    strand = next(c for c in drawn if c.source_path == STRAND)
    limit = bounds_check.tolerance(strand.world_vertices)
    assert _check(stage, plan, _moved(drawn, STRAND, limit / 2)) == []
    problems = _check(stage, plan, _moved(drawn, STRAND, 2 * limit))
    assert any(p.startswith(f"{STRAND}: corner") for p in problems)
    assert any(p.startswith("/World/Placed in the render:") for p in problems)


def test_markers_and_models_with_nothing_compared(tmp_path: Path) -> None:
    # ABND-08: a marker is on neither side, so one that displays vertices fails; the component's only copy is
    # render-only, so in the viewport it expects nothing, and a viewport vertex there fails.
    with evaluation.unsupported_content(tmp_path) as scene:
        stage = scene.stage
        plan = _plan(stage)
        drawn = _drawn(plan)
    fog = next(c for c in drawn if c.source_path == "/World/Fog")
    assert fog.world_vertices == ()
    with_vertex = [dataclasses.replace(c, world_vertices=((0.0, 3.0, 0.0),)) if c is fog else c for c in drawn]
    assert _check(stage, plan, with_vertex) == ["/World/Fog: displays vertices without usable bounds"]
    shown = [dataclasses.replace(c, visible_in_viewport=True) if c.source_path == STRAND else c for c in drawn]
    assert _check(stage, plan, shown) == ["/World/Placed in the viewport: 8 vertices displayed with nothing compared"]
