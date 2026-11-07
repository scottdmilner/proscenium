"""The core's snapshot is a frozen copy: nothing after capture changes it, and what it lends outlives it (M6 plan, B1).

The snapshot is opaque to Python, so each check reads it through the minimal plan, on F-TRANSFORMS' cases
"snapshot-independence" (SNAP-10, SNAP-11).
"""

from __future__ import annotations

import gc
from typing import TYPE_CHECKING, Any

import pytest
from pxr import Gf, Usd

from fixtures import evaluation
from proscenium.core import _core
from support.usd import open_fresh

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

CONTEXT = _core.PlanningContext(unit_scale=1.0, representation_version=1)
EDITED, REMOVED = "/World/Ordered", "/World/Mirrored"


@pytest.fixture
def transforms(tmp_path: Path) -> Iterator[evaluation.TransformsScene]:
    with evaluation.transforms(tmp_path) as scene:
        yield scene


def _contents(plan: _core.Plan) -> tuple[Any, ...]:
    """Everything the plan holds, as plain values."""
    return (
        plan.time_code,
        [p.resources for p in plan.partitions],
        [(r.role, r.entity, r.place, r.covers, r.uses) for r in plan.resources],
        [(c.element, c.source) for c in plan.correspondence],
        [memoryview(b).tolist() for b in (plan.copy_worlds, plan.copy_objects, plan.copy_geometries)],
        [memoryview(b).tolist() for b in (plan.copy_placeholders, plan.placeholder_bounds)],
        [(g.source, memoryview(g.extent).tolist(), g.content_key) for g in plan.geometries],
    )


def _sources(plan: _core.Plan) -> set[str]:
    return {c.source for c in plan.correspondence}


def test_edits_and_time_changes_after_capture_leave_the_snapshot(transforms: evaluation.TransformsScene) -> None:
    stage = transforms.stage
    chain = _core.SceneIndexChain(stage)
    snapshot = chain.capture(Usd.TimeCode(0.0))
    before = _contents(_core.plan(snapshot, CONTEXT))
    stage.GetPrimAtPath(EDITED).GetAttribute("xformOp:translate").Set(Gf.Vec3d(9, 9, 9))
    stage.RemovePrim(REMOVED)
    later = chain.capture(Usd.TimeCode(10.0))  # moves the chain and applies the edits
    try:
        assert _contents(_core.plan(snapshot, CONTEXT)) == before
        # The edits reached the chain, so the check above could fail.
        assert f"{REMOVED}/Geom" in _sources(_core.plan(snapshot, CONTEXT))
        assert f"{REMOVED}/Geom" not in _sources(_core.plan(later, CONTEXT))
    finally:
        chain.release()


def test_lent_buffers_outlive_the_plan_snapshot_chain_and_stage(transforms: evaluation.TransformsScene) -> None:
    stage = open_fresh(transforms.root)
    chain = _core.SceneIndexChain(stage)
    plan = _core.plan(chain.capture(Usd.TimeCode(0.0)), CONTEXT)
    extents = [g.extent for g in plan.geometries]
    # The Tetra's extent.
    assert extents and all(memoryview(e).tolist() == [0.0, 0.0, 0.0, 1.0, 1.0, 1.0] for e in extents)
    lent = [*extents, plan.copy_worlds, plan.copy_objects, plan.copy_geometries]
    values = [memoryview(b).tolist() for b in lent]
    chain.release()
    del plan, chain, stage
    gc.collect()
    assert [memoryview(b).tolist() for b in lent] == values
