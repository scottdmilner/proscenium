"""The plan diff in the core (M7 plan, C4): what a new plan changes from the published one (change-matrix.md).

On F-EDIT-SEQUENCE, each step's plan is diffed with the plan before it, and the copies built, retired, rebuilt, and
updated in place are the ones the fixture names, each updated copy in the list of what its case changes; the settings
cases on the scene as it starts change what the change matrix says, together as apart; a sheared copy moved and a
mesh's extent blocked are local updates. On F-SAME-VALUES, a change of time code changes the copies the fixture says
differ. Every list is in its plan's order. Expected sets come from the fixtures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Usd, UsdGeom

from fixtures import edit_sequence, evaluation, incremental
from proscenium.core import _core

from .plan_checks import CONTEXT, SETTINGS, plan_at

if TYPE_CHECKING:
    from collections.abc import Buffer, Iterator
    from pathlib import Path

    from fixtures.edit_sequence import CopyIdentity, EditSequenceScene
    from fixtures.incremental import SameValuesScene

MOVED, BOUNDS, PARTICIPATION = "moved", "bounds changed", "participation changed"
# What each step that updates copies in place changes of them, by the change matrix's case.
UPDATES_BY_STEP = {
    "ancestor-transform": MOVED,
    "coalesced-transform": MOVED,
    "repeated-transform": MOVED,
    "ancestor-visibility": PARTICIPATION,
    "visibility-restored": PARTICIPATION,
    "purpose-render": PARTICIPATION,
    "bounds-changed": BOUNDS,
    "shared-contents-changed": MOVED,
    "point-moved": MOVED,
    "point-removed-by-index": MOVED,  # each index's copy at the next point's transform
}


@pytest.fixture
def scene(tmp_path: Path) -> Iterator[EditSequenceScene]:
    with edit_sequence.edit_sequence(tmp_path) as scene:
        yield scene


def _identities(plan: _core.Plan) -> list[CopyIdentity]:
    return [(entry.source_path, tuple(entry.instance_context)) for entry in plan.correspondence]


def _indices(buffer: Buffer) -> list[int]:
    with memoryview(buffer) as view:
        return view.tolist()


def _changes(previous: _core.Plan, plan: _core.Plan) -> dict[str, set[CopyIdentity]]:
    """The diff's lists, as the identities of the copies each names."""
    diff = _core.diff_plans(previous, plan)
    before, after = _identities(previous), _identities(plan)
    matched = _indices(diff.previous_copy_indices)
    assert len(matched) == len(after)
    # A kept copy's counterpart has its identity.
    assert all(before[old] == after[new] for new, old in enumerate(matched) if old >= 0)
    named = {
        "rebuilt": diff.rebuilt_copy_indices,
        MOVED: diff.moved_copy_indices,
        BOUNDS: diff.bounds_changed_copy_indices,
        PARTICIPATION: diff.participation_changed_copy_indices,
    }
    named["removed"] = diff.removed_previous_copy_indices
    listed = {name: _indices(buffer) for name, buffer in named.items()}
    assert all(indices == sorted(set(indices)) for indices in listed.values())  # each in its plan's order, once
    removed = listed.pop("removed")
    changes = {name: {after[i] for i in indices} for name, indices in listed.items()}
    changes["built"] = {after[new] for new, old in enumerate(matched) if old < 0}
    changes["retired"] = {before[i] for i in removed}
    return changes


def _expected(
    built: frozenset[CopyIdentity] = frozenset(),
    retired: frozenset[CopyIdentity] = frozenset(),
    rebuilt: frozenset[CopyIdentity] = frozenset(),
    **updated: frozenset[CopyIdentity],
) -> dict[str, set[CopyIdentity]]:
    expected = {name: set() for name in ("rebuilt", MOVED, BOUNDS, PARTICIPATION)}
    expected |= {"built": set(built), "retired": set(retired), "rebuilt": set(rebuilt)}
    for name, copies in updated.items():
        expected[name.replace("_", " ")] = set(copies)
    return expected


def test_an_equal_plan_changes_nothing(scene: EditSequenceScene) -> None:
    # Two captures through two chains: equal plans, each copy matched to itself.
    previous, plan = plan_at(scene.stage, 0.0), plan_at(scene.stage, 0.0)
    assert _changes(previous, plan) == _expected()
    assert _indices(_core.diff_plans(previous, plan).previous_copy_indices) == list(range(len(previous.correspondence)))


def test_each_step_changes_what_the_fixture_names(scene: EditSequenceScene) -> None:
    previous = plan_at(scene.stage, 0.0)
    assert set(_identities(previous)) == scene.initial_copies
    for step in scene.steps:
        step.edit(scene.stage)
        plan = plan_at(scene.stage, 0.0)
        updated = {UPDATES_BY_STEP[step.name].replace(" ", "_"): step.updated} if step.updated else {}
        expected = _expected(step.built, step.retired, step.rebuilt, **updated)
        assert _changes(previous, plan) == expected, step.name
        previous = plan


def _replanned(
    stage: Usd.Stage, settings: _core.PlanSettings, context: _core.PlanningContext
) -> tuple[_core.Plan, _core.Plan]:
    """The plan under the default settings and context, and from the same snapshot under the given ones."""
    chain = _core.SceneIndexChain(stage)
    try:
        snapshot = chain.capture(Usd.TimeCode(0.0))
    finally:
        chain.release()
    return _core.plan(snapshot, SETTINGS, CONTEXT), _core.plan(snapshot, settings, context)


@pytest.mark.parametrize(
    "settings",
    [
        _core.PlanSettings(["proxy"], evaluation.RENDER_PURPOSES),
        _core.PlanSettings(evaluation.VIEWPORT_PURPOSES, ["render"]),
    ],
    ids=["viewport", "render"],
)
def test_a_destinations_purposes_change_participation(scene: EditSequenceScene, settings: _core.PlanSettings) -> None:
    # A destination without default: every copy, each of default purpose and visible, leaves that destination only.
    previous, plan = _replanned(scene.stage, settings, CONTEXT)
    assert _changes(previous, plan) == _expected(participation_changed=scene.initial_copies)


def test_coordinate_conversion_moves_every_copy(scene: EditSequenceScene) -> None:
    # The stage is Z-up in meters, so conversion at a unit scale of 1 is the identity, and at 2 scales every copy.
    converted = _core.PlanSettings(evaluation.VIEWPORT_PURPOSES, evaluation.RENDER_PURPOSES, coordinate_conversion=True)
    previous, plan = _replanned(scene.stage, converted, _core.PlanningContext(2.0, 1))
    assert _changes(previous, plan) == _expected(moved=scene.initial_copies)


def test_a_copy_can_change_in_several_ways_at_once(scene: EditSequenceScene) -> None:
    # Conversion at a unit scale of 2 and a viewport without default: every copy moved and its participation changed.
    settings = _core.PlanSettings(["proxy"], evaluation.RENDER_PURPOSES, coordinate_conversion=True)
    previous, plan = _replanned(scene.stage, settings, _core.PlanningContext(2.0, 1))
    assert _changes(previous, plan) == _expected(moved=scene.initial_copies, participation_changed=scene.initial_copies)


def test_one_copys_three_local_updates_are_each_listed(scene: EditSequenceScene) -> None:
    # Odd, a placeholder box, translated, its bounds changed, and made invisible before one plan.
    odd, previous = scene.stage.GetPrimAtPath(edit_sequence.ODD), plan_at(scene.stage, 0.0)
    scene.stage.GetAttributeAtPath(f"{edit_sequence.ODD}.xformOp:translate").Set(Gf.Vec3d(7, 0, 0))
    UsdGeom.Boundable(odd).GetExtentAttr().Set([Gf.Vec3f(0, 0, 0), Gf.Vec3f(2, 2, 2)])
    UsdGeom.Imageable(odd).MakeInvisible()
    copy = frozenset({(edit_sequence.ODD, ())})
    expected = _expected(moved=copy, bounds_changed=copy, participation_changed=copy)
    assert _changes(previous, plan_at(scene.stage, 0.0)) == expected


def test_copies_removed_together_are_listed_in_order(scene: EditSequenceScene) -> None:
    previous = plan_at(scene.stage, 0.0)
    scene.stage.GetPrimAtPath(edit_sequence.GROUP).SetActive(False)
    retired = frozenset({(edit_sequence.A, ()), (edit_sequence.B, ())})
    assert _changes(previous, plan_at(scene.stage, 0.0)) == _expected(retired=retired)


def test_a_sheared_copy_moved_is_moved(scene: EditSequenceScene) -> None:
    # The fixture's shear-introduced step shears A, which then keeps its shear parent as it moves.
    shear = next(step for step in scene.steps if step.name == "shear-introduced")
    shear.edit(scene.stage)
    previous = plan_at(scene.stage, 0.0)
    scene.stage.GetAttributeAtPath(f"{edit_sequence.A}.xformOp:translate").Set(Gf.Vec3d(0, 0, 3))
    assert _changes(previous, plan_at(scene.stage, 0.0)) == _expected(moved=frozenset({(edit_sequence.A, ())}))


def test_a_meshs_extent_blocked_and_restored_changes_its_bounds(scene: EditSequenceScene) -> None:
    # Without an extent a mesh's bounds mesh has no vertices, but stays: its partition holds the same resources.
    a = frozenset({(edit_sequence.A, ())})
    extent = UsdGeom.Boundable(scene.stage.GetPrimAtPath(edit_sequence.A)).GetExtentAttr()
    authored, previous = extent.Get(), plan_at(scene.stage, 0.0)
    extent.Block()
    blocked = plan_at(scene.stage, 0.0)
    assert _changes(previous, blocked) == _expected(bounds_changed=a)
    extent.Set(authored)
    assert _changes(blocked, plan_at(scene.stage, 0.0)) == _expected(bounds_changed=a)


@pytest.fixture
def same_values(tmp_path: Path) -> Iterator[SameValuesScene]:
    with incremental.same_values(tmp_path) as scene:
        yield scene


def _time_code(value: float | None) -> Usd.TimeCode:
    return Usd.TimeCode.Default() if value is None else Usd.TimeCode(value)


@pytest.mark.parametrize(
    ("first", "second"), [(0.0, 5.0), (5.0, 15.0), (15.0, 25.0), (10.0, 15.0), (12.5, 17.5), (0.0, None)]
)
def test_a_time_code_change_changes_the_copies_whose_values_differ(
    same_values: SameValuesScene, first: float | None, second: float | None
) -> None:
    # Held's translate moves it and Blink's visibility changes its participation; equal values change nothing.
    chain = _core.SceneIndexChain(same_values.stage)
    try:
        previous, plan = (_core.plan(chain.capture(_time_code(t)), SETTINGS, CONTEXT) for t in (first, second))
    finally:
        chain.release()
    changed = same_values.changed_copies(first, second)
    moved = frozenset({(incremental.HELD, ())} if incremental.HELD in changed else ())
    blinked = frozenset({(incremental.BLINK, ())} if incremental.BLINK in changed else ())
    assert _changes(previous, plan) == _expected(moved=moved, participation_changed=blinked)


def test_unit_scale_without_conversion_changes_nothing(scene: EditSequenceScene) -> None:
    previous, plan = _replanned(scene.stage, SETTINGS, _core.PlanningContext(2.0, 1))
    assert _changes(previous, plan) == _expected()
