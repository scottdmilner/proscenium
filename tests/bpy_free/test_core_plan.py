"""The core captures a snapshot through its Hydra chain and plans a drawn copy per drawn gprim (M5 plan, Phase B).

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
from proscenium.binding.source_access.stages import PayloadPolicy
from proscenium.core import _core
from support.usd import open_fresh

from .plan_checks import CONTEXT, SETTINGS, copies

if TYPE_CHECKING:
    from pathlib import Path

TIME_CODES = [None, 0.0, 7.5, 10.0, 20.0]


def _time_code(time_code: float | None) -> Usd.TimeCode:
    return Usd.TimeCode.Default() if time_code is None else Usd.TimeCode(time_code)


def _plan(stage: Usd.Stage, time_code: float | None = 0.0) -> _core.Plan:
    return _core.plan(_core.SceneIndexChain(stage).capture(_time_code(time_code)), SETTINGS, CONTEXT)


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


def _identity(resource: _core.Resource) -> tuple[str, str, int]:
    """A copy's resource's identity: its role, its copy's source entity, and its place among the copy's objects."""
    return (resource.role, resource.entity, resource.place)


@pytest.mark.parametrize("policy", list(PayloadPolicy))
def test_a_copy_per_drawn_gprim(policy: PayloadPolicy, tmp_path: Path) -> None:
    with transaction.failed_settings(tmp_path) as scene:
        plan = _plan(open_fresh(scene.root, policy.load_set))
        shown = copies(plan)
        assert shown.keys() == DRAWN[policy]
        assert plan.copy_count == len(shown) == len(plan.correspondence)
        for copy in shown.values():
            assert copy.bounds == (*EXTENT[0], *EXTENT[1])  # each a mesh's, with no placeholder
            assert (copy.geometry >= 0, copy.placeholder) == (True, -1)


def test_copy_content_crosses_as_blenders_element_types(tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        plan = _plan(scene.caller)
    count = plan.copy_count
    buffers = {
        "copy_worlds": ("f", 16 * count),
        "copy_objects": ("i", count),
        "copy_geometries": ("i", count),
        "copy_placeholders": ("i", count),
        "placeholder_bounds": ("f", 0),  # the scene's gprims are all meshes
    }
    for name, (element, length) in buffers.items():
        view = memoryview(getattr(plan, name))
        assert (view.format, view.ndim, view.readonly, len(view)) == (element, 1, True, length), name
    for geometry in plan.geometries:
        view = memoryview(geometry.extent)
        assert (view.format, view.ndim, view.readonly, len(view)) == ("f", 1, True, 6)


@pytest.mark.parametrize("time_code", TIME_CODES)
def test_world_transforms_at_the_time_code(time_code: float | None, tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        plan = _plan(scene.caller, time_code)
        assert plan.time_code == _time_code(time_code)
        for source, copy in copies(plan).items():
            assert copy.world.ExtractTranslation() == translation(source, time_code)


def test_ownership_entries_partitions_and_correspondence(tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        plan = _plan(scene.caller)
        assert len({_identity(r) for r in plan.resources}) == transaction.resource_count(PayloadPolicy.LOAD_ALL)
        assert len(plan.resources) == transaction.resource_count(PayloadPolicy.LOAD_ALL)
        shown = copies(plan)
        for source, copy in shown.items():
            assert copy.bounds_mesh is not None  # the scene's gprims are all meshes
            obj, mesh = plan.resources[copy.object], plan.resources[copy.bounds_mesh]
            assert (obj.role, obj.covers, obj.uses) == ("object", (source,), (copy.bounds_mesh,))
            assert (mesh.role, mesh.covers, mesh.uses) == ("bounds mesh", (source,), ())
        assert sorted(p.resources for p in plan.partitions) == sorted((c.object, c.bounds_mesh) for c in shown.values())
        assert sorted((c.element, c.source) for c in plan.correspondence) == sorted(
            (c.object, source) for source, c in shown.items()
        )


def test_identities_follow_role_and_source_entity(tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        for time_code in TIME_CODES:
            plan = _plan(scene.caller, time_code)
            for source, copy in copies(plan).items():
                assert copy.bounds_mesh is not None
                assert _identity(plan.resources[copy.object]) == ("object", source, 0)
                assert _identity(plan.resources[copy.bounds_mesh]) == ("bounds mesh", source, 0)


def test_planning_is_deterministic(tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        snapshot = _core.SceneIndexChain(scene.caller).capture(10.0)
        assert _contents(_core.plan(snapshot, SETTINGS, CONTEXT)) == _contents(_core.plan(snapshot, SETTINGS, CONTEXT))
        assert _contents(_core.plan(snapshot, SETTINGS, CONTEXT)) == _contents(_plan(scene.caller, 10.0))


def test_snapshot_outlives_edits_and_release(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        chain = _core.SceneIndexChain(scene.caller)
        before = chain.capture(0.0)
        planned = _contents(_core.plan(before, SETTINGS, CONTEXT))
        scene.edit()
        after = copies(_core.plan(chain.capture(0.0), SETTINGS, CONTEXT))
        assert after["/World/Sub"].world.ExtractTranslation() == SUB_EDITED
        chain.release()
        # Neither the edit nor the released chain reaches what the first capture copied.
        assert _contents(_core.plan(before, SETTINGS, CONTEXT)) == planned
        assert copies(_core.plan(before, SETTINGS, CONTEXT))["/World/Sub"].world.ExtractTranslation() == translation(
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
            _core.plan(snapshot, SETTINGS, _core.PlanningContext(1.0, 2))
