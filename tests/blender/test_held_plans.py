"""The held plans (DECISIONS.md "Incremental refresh comparison"; M7 plan, C5), on F-EDIT-SEQUENCE.

Each synchronization that publishes holds its plan under its generation record, found again by the record the
destination holds: after an undo or redo, the restored generation's; after caching a time code, whose record then names
it, the same; past the bound Blender's undo steps set, none for the oldest; and after reopening, or once the binding is
released, none. The plan a synchronization published is the one application prepared, recorded by wrapping it.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, cast

import bpy
import pytest
from pxr import Gf

from fixtures import edit_sequence
from proscenium_sync.api import bindings as api
from proscenium_sync.binding_persistence import binding_state, id_property_records
from proscenium_sync.binding_runtime import held_plans
from proscenium_sync.results import ResultState
from proscenium_sync.synchronization import application
from support import undo
from support.blend import save_and_reopen
from support.destinations import destination

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fixtures.edit_sequence import EditSequenceScene
    from proscenium_sync import core
    from proscenium_sync.api.bindings import BindingHandle, Bindings
    from proscenium_sync.binding_persistence.binding_state import GenerationMetadata


@pytest.fixture
def scene(tmp_path: Path) -> Iterator[EditSequenceScene]:
    with edit_sequence.edit_sequence(tmp_path) as scene:
        yield scene


@pytest.fixture
def prepared(monkeypatch: pytest.MonkeyPatch) -> list[core.Plan]:
    """The plans application prepared, in order."""
    plans: list[core.Plan] = []
    prepare = application.prepare

    def recording_prepare(plan: core.Plan, *rest: object) -> None:
        plans.append(plan)
        prepare(plan, *rest)  # ty: ignore[invalid-argument-type] - prepare's own arguments

    monkeypatch.setattr(application, "prepare", recording_prepare)
    return plans


def _binding(bindings: Bindings, scene: EditSequenceScene) -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
    assert handle.attach(scene.stage).state is ResultState.SUCCESS
    return handle


def _shown(name: str = "Shot") -> GenerationMetadata:
    shown = binding_state.read_generation(bpy.data.collections[name])
    assert isinstance(shown, id_property_records.LoadedRecord)
    return shown.record


def _synchronized(handle: BindingHandle) -> GenerationMetadata:
    assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
    return _shown()


def _move_a(scene: EditSequenceScene, z: float) -> None:
    scene.stage.GetAttributeAtPath(f"{edit_sequence.A}.xformOp:translate").Set(Gf.Vec3d(0, 0, z))


def test_each_published_generation_holds_its_plan(
    bindings: Bindings, scene: EditSequenceScene, prepared: list[core.Plan]
) -> None:
    handle = _binding(bindings, scene)
    first = _synchronized(handle)
    _move_a(scene, 1)
    second = _synchronized(handle)
    assert first.source_revision != second.source_revision
    assert bindings.published_plans.plan_for(first) is prepared[0]
    assert bindings.published_plans.plan_for(second) is prepared[1]
    # Nothing changed, so a full rebuild publishes an equal record, which names its plan from then on.
    assert handle.synchronize(0, full_rebuild=True).state is not ResultState.FATAL_FAILURE
    assert _shown() == second
    assert bindings.published_plans.plan_for(second) is prepared[2]


def test_undo_and_redo_find_the_restored_generations_plan(
    bindings: Bindings, scene: EditSequenceScene, prepared: list[core.Plan], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each synchronization pushes its undo step, as Blender with global undo on, outside background mode, would.
    undo.require_global_undo()
    monkeypatch.setattr(api, "_undo_steps_enabled", lambda: True)
    handle = _binding(bindings, scene)
    undo.push("base")
    first = _synchronized(handle)
    _move_a(scene, 1)
    second = _synchronized(handle)
    undo.undo()
    assert _shown() == first
    assert bindings.published_plans.plan_for(_shown()) is prepared[0]
    undo.redo()
    assert _shown() == second
    assert bindings.published_plans.plan_for(_shown()) is prepared[1]


def test_a_cached_time_code_keeps_the_generations_plan(
    bindings: Bindings, scene: EditSequenceScene, prepared: list[core.Plan]
) -> None:
    handle = _binding(bindings, scene)
    _synchronized(handle)
    assert handle.cache([scene.cached_time_codes[0]]).state is not ResultState.FATAL_FAILURE
    assert _shown().cached_time_codes == (scene.cached_time_codes[0],)
    assert bindings.published_plans.plan_for(_shown()) is prepared[0]


def test_the_oldest_plan_goes_past_the_undo_steps(
    bindings: Bindings, scene: EditSequenceScene, prepared: list[core.Plan], monkeypatch: pytest.MonkeyPatch
) -> None:
    # With two undo steps, Blender's least, a binding holds three plans: the generation shown, and two an undo restores.
    preferences = bpy.context.preferences
    assert preferences is not None
    monkeypatch.setattr(preferences.edit, "undo_steps", 2)
    handle = _binding(bindings, scene)
    published = []
    for z in (1, 2, 3, 4):
        _move_a(scene, z)
        published.append(_synchronized(handle))
    assert [bindings.published_plans.plan_for(g) for g in published] == [None, *prepared[1:]]


def test_reopening_holds_none(bindings: Bindings, scene: EditSequenceScene, tmp_path: Path) -> None:
    # Its source revisions are the process's, but the file's records outlive the held plans, which a load clears.
    handle = _binding(bindings, scene)
    published = _synchronized(handle)
    save_and_reopen(tmp_path / "held.blend")
    assert _shown() == published
    assert bindings.published_plans.plan_for(_shown()) is None


def test_a_released_binding_holds_none(bindings: Bindings, scene: EditSequenceScene) -> None:
    handle = _binding(bindings, scene)
    published = _synchronized(handle)
    assert bindings.published_plans.plan_for(published) is not None
    bindings.release(handle.binding_id)
    assert _shown(destination(handle).name) == published
    assert bindings.published_plans.plan_for(published) is None


def test_a_record_held_again_is_the_newest(bindings: Bindings, scene: EditSequenceScene) -> None:
    # Records differing only in their time code, each held with a plan of its own, two at a time.
    record = _synchronized(_binding(bindings, scene))
    first, second, third = (dataclasses.replace(record, time_code=t) for t in (1.0, 2.0, 3.0))
    plans = {name: cast("core.Plan", object()) for name in ("first", "second", "again", "third")}
    published_plans = held_plans.HeldPlans()
    published_plans.hold(first, plans["first"], 2)
    published_plans.hold(second, plans["second"], 2)
    published_plans.hold(first, plans["again"], 2)
    published_plans.hold(third, plans["third"], 2)
    assert [published_plans.plan_for(g) for g in (first, second, third)] == [plans["again"], None, plans["third"]]
    with pytest.raises(ValueError, match="at least"):
        published_plans.hold(first, plans["first"], 0)
