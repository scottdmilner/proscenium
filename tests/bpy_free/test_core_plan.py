"""The core captures a snapshot through its Hydra chain and plans a placeholder per drawn gprim (M5 plan, Phase B).

Expected values come from how the transaction scenes are built (fixtures/transaction.py, checked against UsdGeom by
test_transaction_fixtures.py), and identities from what the spec derives them from (lifecycle.md, Representation Roles
and Resource Identities).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pxr import Usd

from fixtures import transaction
from fixtures.transaction import DRAWN, EXTENT, SUB_EDITED, translation
from proscenium.binding.source_access import PayloadPolicy
from proscenium.core import _core
from support.usd import open_fresh

if TYPE_CHECKING:
    from pathlib import Path

CONTEXT = _core.PlanningContext(unit_scale=1.0, representation_version=1)
TIME_CODES = [None, 0.0, 7.5, 10.0, 20.0]


def _time_code(time_code: float | None) -> Usd.TimeCode:
    return Usd.TimeCode.Default() if time_code is None else Usd.TimeCode(time_code)


def _plan(stage: Usd.Stage, time_code: float | None = 0.0) -> _core.Plan:
    return _core.plan(_core.SceneIndexChain(stage).capture(_time_code(time_code)), CONTEXT)


def _contents(plan: _core.Plan) -> tuple[Any, ...]:
    """Everything the plan holds, as plain values."""
    return (
        plan.time_code,
        [p.resources for p in plan.partitions],
        [(r.role, r.entity, r.place, r.covers, r.uses) for r in plan.resources],
        [(c.element, c.source) for c in plan.correspondence],
        [(p.object, p.bounds_mesh, p.world, list(p.bounds)) for p in plan.placeholders],
    )


def _sources(plan: _core.Plan) -> dict[str, _core.Placeholder]:
    """Each placeholder by the source path its object covers."""
    return {plan.resources[p.object].covers[0]: p for p in plan.placeholders}


def _identity(resource: _core.Resource) -> tuple[str, str, int]:
    """A copy's resource's identity: its role, its copy's source entity, and its place among the copy's objects."""
    return (resource.role, resource.entity, resource.place)


@pytest.mark.parametrize("policy", list(PayloadPolicy))
def test_a_placeholder_per_drawn_gprim(policy: PayloadPolicy, tmp_path: Path) -> None:
    with transaction.failed_settings(tmp_path) as scene:
        plan = _plan(open_fresh(scene.root, policy.load_set))
        placeholders = _sources(plan)
        assert placeholders.keys() == DRAWN[policy]
        for placeholder in placeholders.values():
            assert list(placeholder.bounds) == [*EXTENT[0], *EXTENT[1]]
            view = memoryview(placeholder.bounds)  # ty: ignore[invalid-argument-type] - the stubs omit Vt's buffers
            assert (view.format, view.ndim, view.readonly) == ("f", 1, True)


@pytest.mark.parametrize("time_code", TIME_CODES)
def test_world_transforms_at_the_time_code(time_code: float | None, tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        plan = _plan(scene.caller, time_code)
        assert plan.time_code == _time_code(time_code)
        for source, placeholder in _sources(plan).items():
            assert placeholder.world.ExtractTranslation() == translation(source, time_code)


def test_ownership_entries_partitions_and_correspondence(tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        plan = _plan(scene.caller)
        assert len({_identity(r) for r in plan.resources}) == transaction.resource_count(PayloadPolicy.LOAD_ALL)
        assert len(plan.resources) == transaction.resource_count(PayloadPolicy.LOAD_ALL)
        for source, placeholder in _sources(plan).items():
            obj, mesh = plan.resources[placeholder.object], plan.resources[placeholder.bounds_mesh]
            assert (obj.role, obj.covers, obj.uses) == ("object", (source,), (placeholder.bounds_mesh,))
            assert (mesh.role, mesh.covers, mesh.uses) == ("bounds mesh", (source,), ())
        assert sorted(p.resources for p in plan.partitions) == sorted(
            (p.object, p.bounds_mesh) for p in plan.placeholders
        )
        assert sorted((c.element, c.source) for c in plan.correspondence) == sorted(
            (p.object, source) for source, p in _sources(plan).items()
        )


def test_identities_follow_role_and_source_entity(tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        for time_code in TIME_CODES:
            plan = _plan(scene.caller, time_code)
            for source, placeholder in _sources(plan).items():
                assert _identity(plan.resources[placeholder.object]) == ("object", source, 0)
                assert _identity(plan.resources[placeholder.bounds_mesh]) == ("bounds mesh", source, 0)


def test_planning_is_deterministic(tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        snapshot = _core.SceneIndexChain(scene.caller).capture(10.0)
        assert _contents(_core.plan(snapshot, CONTEXT)) == _contents(_core.plan(snapshot, CONTEXT))
        assert _contents(_core.plan(snapshot, CONTEXT)) == _contents(_plan(scene.caller, 10.0))


def test_snapshot_outlives_edits_and_release(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        chain = _core.SceneIndexChain(scene.caller)
        before = chain.capture(0.0)
        planned = _contents(_core.plan(before, CONTEXT))
        scene.edit()
        after = _sources(_core.plan(chain.capture(0.0), CONTEXT))
        assert after["/World/Sub"].world.ExtractTranslation() == SUB_EDITED
        chain.release()
        # Neither the edit nor the released chain reaches what the first capture copied.
        assert _contents(_core.plan(before, CONTEXT)) == planned
        assert _sources(_core.plan(before, CONTEXT))["/World/Sub"].world.ExtractTranslation() == translation(
            "/World/Sub", 0.0
        )


def test_released_chain_refuses_capture(tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        chain = _core.SceneIndexChain(scene.caller)
        chain.release()
        chain.release()  # idempotent
        assert chain.released
        with pytest.raises(RuntimeError, match="released"):
            chain.capture(0.0)


def test_invalid_stage_raises() -> None:
    with pytest.raises(ValueError, match="valid USD stage"):
        _core.SceneIndexChain(None)


@pytest.mark.parametrize("unit_scale", [0.0, -1.0, float("inf"), float("nan")])
def test_context_refuses_a_unit_scale(unit_scale: float) -> None:
    with pytest.raises(ValueError, match="unit scale"):
        _core.PlanningContext(unit_scale, 1)


def test_planner_refuses_another_representation_version(tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        snapshot = _core.SceneIndexChain(scene.caller).capture(0.0)
        with pytest.raises(ValueError, match="representation version"):
            _core.plan(snapshot, _core.PlanningContext(1.0, 2))
