"""Coordinate conversion in the plan, on F-UNITS-UP-AXIS (M6 plan, C3).

With conversion off, the default, every world transform is its USD world transform (case "conversion-off",
CONV-01). With it on, planning prefixes the spec's correction matrix to every world transform, the mesh's and the
instance's alike, and local bounds are unchanged (case "conversion-on", CONV-03, CONV-08). Expected values come from
the fixture's construction and its correction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Usd, UsdGeom

from fixtures import evaluation
from fixtures.evaluation import RENDER_PURPOSES, VIEWPORT_PURPOSES
from proscenium.core import _core

from .plan_checks import SETTINGS, assert_world, copies

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

CONVERTING = _core.PlanSettings(VIEWPORT_PURPOSES, RENDER_PURPOSES, coordinate_conversion=True)
SCALE_LENGTHS = [1.0, 0.01]  # the target scene's unit scale


@pytest.fixture
def units(tmp_path: Path) -> Iterator[evaluation.UnitsScene]:
    with evaluation.units_up_axis(tmp_path) as scene:
        yield scene


def _snapshot(stage: Usd.Stage) -> _core.Snapshot:
    chain = _core.SceneIndexChain(stage)
    try:
        return chain.capture(Usd.TimeCode(0.0))
    finally:
        chain.release()


def _plan(snapshot: _core.Snapshot, settings: _core.PlanSettings, scale_length: float) -> _core.Plan:
    return _core.plan(snapshot, settings, _core.PlanningContext(scale_length, 1))


@pytest.mark.parametrize("scale_length", SCALE_LENGTHS)
@pytest.mark.parametrize("stage", ["y-up-cm", "z-up-m"])
def test_conversion_off_keeps_usd_world_transforms(
    units: evaluation.UnitsScene, stage: str, scale_length: float
) -> None:
    shown = copies(_plan(_snapshot(units.stages[stage]), SETTINGS, scale_length))
    assert shown.keys() == units.world.keys()
    for path, copy in shown.items():
        assert_world(copy, units.world[path])


@pytest.mark.parametrize("scale_length", SCALE_LENGTHS)
@pytest.mark.parametrize("stage", ["y-up-cm", "z-up-m"])
def test_conversion_prefixes_the_correction(units: evaluation.UnitsScene, stage: str, scale_length: float) -> None:
    """Relation 2, conversion (CONV-01, CONV-03, CONV-08).

    Input: coordinate_conversion turned on, planning one snapshot under both settings, so only the setting differs.
    Effect: each drawn copy's world transform W becomes W · C, C the spec's correction for the stage's metersPerUnit
    and upAxis and the target scene's unit scale, so a Z-up stage in meters into a scene of unit scale 1 plans as with
    conversion off; local bounds, sources, instance contexts, participation, and diagnostics are unchanged. On
    F-UNITS-UP-AXIS' stages; a sheared copy's objects are test_relations.py's, on generated hierarchies.
    """
    snapshot = _snapshot(units.stages[stage])
    off = _plan(snapshot, SETTINGS, scale_length)
    on = _plan(snapshot, CONVERTING, scale_length)
    correction = units.correction(stage, scale_length)
    converted = copies(on)
    for path, copy in converted.items():
        assert_world(copy, units.world[path] * correction)
        assert copy.bounds == (*units.bounds[0], *units.bounds[1]), path  # local bounds unchanged
    assert {p: (c.bounds, c.viewport, c.render, c.geometry) for p, c in converted.items()} == {
        p: (c.bounds, c.viewport, c.render, c.geometry) for p, c in copies(off).items()
    }
    assert [(c.source, c.instance_context) for c in on.correspondence] == [
        (c.source, c.instance_context) for c in off.correspondence
    ]
    assert [(d.code, d.source_path, d.message) for d in on.diagnostics] == [
        (d.code, d.source_path, d.message) for d in off.diagnostics
    ]


def test_a_z_up_stage_in_meters_into_a_scene_of_scale_1_plans_as_with_conversion_off(
    units: evaluation.UnitsScene,
) -> None:
    # CONV-08: the correction is the identity there.
    snapshot = _snapshot(units.stages["z-up-m"])
    assert (
        memoryview(_plan(snapshot, CONVERTING, 1.0).copy_worlds).tolist()
        == memoryview(_plan(snapshot, SETTINGS, 1.0).copy_worlds).tolist()
    )


def test_the_snapshot_keeps_the_stages_units_and_up_axis(units: evaluation.UnitsScene) -> None:
    # Editing the stage's metadata after capture reaches only a later capture.
    stage = units.stages["y-up-cm"]
    chain = _core.SceneIndexChain(stage)
    try:
        before = chain.capture(Usd.TimeCode(0.0))
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        after = chain.capture(Usd.TimeCode(0.0))
    finally:
        chain.release()
    for path, copy in copies(_plan(before, CONVERTING, 1.0)).items():
        assert_world(copy, units.world[path] * units.correction("y-up-cm", 1.0))
    for path, copy in copies(_plan(after, CONVERTING, 1.0)).items():
        assert_world(copy, units.world[path])  # meters and Z up: the identity
