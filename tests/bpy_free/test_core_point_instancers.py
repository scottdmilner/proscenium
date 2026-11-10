"""Point instancers' copies through the plan, on F-POINT-INSTANCERS (M6 plan, C11).

Each point's copies of its prototype are drawn copies with the point's transform and visibility (INST-08), named by
point-instance paths, by authored id or by index, with the instancer and the point in their instance contexts, inside
native instances too (ICON-42), the context's first entry their floor (ICON-19). Expected values come from the
fixture, which tests/bpy_free/test_evaluation_fixtures.py checks against UsdGeom.PointInstancer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Sdf, Usd, Vt

from fixtures import evaluation
from proscenium.binding.source_access import source_entities
from proscenium.core import _core

from .plan_checks import CONTEXT, SETTINGS, assert_world, copies, plan_at

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def points(tmp_path: Path) -> Iterator[evaluation.PointInstancerScene]:
    with evaluation.point_instancers(tmp_path) as scene:
        yield scene


def test_each_point_draws_its_prototype(points: evaluation.PointInstancerScene) -> None:
    # INST-08: a copy per point and prototype mesh, Pebble's native instance's included, at the fixture's world
    # transform; the points invisibleIds hides in neither destination; nothing for a prototype prim at its own path.
    plan = plan_at(points.stage, 0.0)
    shown = copies(plan)
    assert shown.keys() == points.world.keys()
    for path, copy in shown.items():
        assert_world(copy, points.world[path])
        hidden = path in points.invisible
        assert (copy.visible_in_viewport, copy.visible_in_render) == (not hidden, not hidden), path
        assert copy.geometry_index >= 0, path  # a mesh's copy
    assert shown.keys().isdisjoint(points.prototypes)
    # Only UsdImaging's warning about Wisp, which no point draws, named by its own path on the stage.
    assert [(d.code, d.source_path) for d in plan.diagnostics] == [("usd-warning", "/World/Scatter/Protos/Wisp")]


def test_copies_are_named_by_point_instance_paths(points: evaluation.PointInstancerScene) -> None:
    # ICON-42: each copy's source entity is its point-instance path, a valid identifier, with its instance context;
    # ICON-19's floor, the outermost native-instance root or point instancer, leads the context.
    plan = plan_at(points.stage, 0.0)
    entries = {c.source_path: c.instance_context for c in plan.correspondence}
    assert entries == points.instance_context
    for path, context in entries.items():
        assert source_entities.identifier(Sdf.Path(path)) == path
        assert context[0] == points.floors[path], path
    resources = plan.resources
    assert {r.source_entity_path for r in resources} == points.world.keys()
    assert len({(r.role, r.source_entity_path, r.object_index_in_copy) for r in resources}) == len(
        resources
    )  # each copy its own identity


def test_animated_ids_name_each_capture(points: evaluation.PointInstancerScene) -> None:
    # Ids are read at the chain's time, so a point's copy is named by its id at each capture.
    tagged = points.stage.GetPrimAtPath("/World/Tagged").GetAttribute("ids")
    tagged.Set(Vt.Int64Array([10, -3, 7]), Usd.TimeCode(0.0))
    tagged.Set(Vt.Int64Array([11, -3, 7]), Usd.TimeCode(10.0))
    chain = _core.SceneIndexChain(points.stage)
    try:
        shown = {t: set(copies(_core.plan(chain.capture(Usd.TimeCode(t)), SETTINGS, CONTEXT))) for t in (0.0, 10.0)}
    finally:
        chain.release()
    assert "/World/Tagged/__id_10/Rock" in shown[0.0] - shown[10.0]
    assert "/World/Tagged/__id_11/Rock" in shown[10.0] - shown[0.0]
    assert "/World/Tagged/__id_n3/Rock" in shown[0.0] & shown[10.0]
