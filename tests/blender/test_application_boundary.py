"""The application layer's boundary with the plan (pipeline.md#blender-application), on F-NO-OP-REFRESH.

F-NO-OP-REFRESH has a drawn copy of each kind M7's application makes: a mesh, a sheared mesh, a placeholder box, an
empty marker, an invisible and a render-only mesh, and a prototype's mesh through two native instances.
"""

from __future__ import annotations

import gc
import weakref
from typing import TYPE_CHECKING

import bpy
from pxr import Usd

from fixtures import evaluation, incremental
from proscenium import core
from proscenium.binding.persistence import binding_state, id_property_records
from proscenium.binding.persistence.cleanup_ledgers import OriginatingOperation
from proscenium.binding.persistence.manifests import Manifest, RepresentationRole
from proscenium.binding.results import ResultState
from proscenium.synchronization import application, preparation_resources
from support.destinations import destination
from support.usd import binding_on_file, open_stage_without_cache

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from proscenium.api.bindings import Bindings

CONTEXT = core.PlanningContext(unit_scale=1.0, representation_version=application.REPRESENTATION_VERSION)
SETTINGS = core.PlanSettings(evaluation.VIEWPORT_PURPOSES, evaluation.RENDER_PURPOSES)  # the defaults


def _open_plan_views() -> set[int]:
    """The ids of the memoryviews still open on a Vt array, as a plan's buffers are."""
    found = set()
    for candidate in gc.get_objects():
        if isinstance(candidate, memoryview):
            try:
                exporter = candidate.obj
            except ValueError:  # released
                continue
            if type(exporter).__module__ == "pxr.Vt":
                found.add(id(candidate))
    return found


def test_nothing_borrowed_outlives_a_synchronization(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # SNAP-13: once each synchronization returns, every view of its plan's buffers is released, and only the held plans
    # hold the plan, as the shown generation's, so releasing them releases it.
    plans: list[weakref.ref[core.Plan]] = []
    prepare = application.prepare

    def recording_prepare(plan: core.Plan, *rest: object) -> None:
        plans.append(weakref.ref(plan))
        prepare(plan, *rest)  # ty: ignore[invalid-argument-type] - prepare's own arguments

    monkeypatch.setattr(application, "prepare", recording_prepare)
    with incremental.no_op_refresh(tmp_path) as scene:
        handle = binding_on_file(bindings, bpy.data.scenes["Scene"], scene.root_layer_path)
        before = _open_plan_views()
        for attempt in range(2):  # a first synchronization, and one replacing its display
            assert handle.synchronize(0).state is ResultState.COMPLETED_WITH_ISSUES  # its placeholders warn
            gc.collect()
            assert len(plans) == attempt + 1
            assert _open_plan_views() <= before
            shown = binding_state.read_generation(destination(handle))
            assert isinstance(shown, id_property_records.LoadedRecord)
            assert bindings.published_plans.plan_for(shown.record) is plans[-1]()
        bindings.release(handle.binding_id)
        gc.collect()
        assert all(plan() is None for plan in plans)


def test_a_plan_is_prepared_without_its_stage(bindings: Bindings, tmp_path: Path) -> None:
    # APP-08: the plan holds all application reads, so with its chain released and its stage gone, preparing it still
    # makes each copy's partition: an object per copy, a bounds mesh for each but the marker, and the sheared copy's
    # shear parent.
    with incremental.no_op_refresh(tmp_path) as scene:
        stage = open_stage_without_cache(scene.root_layer_path)
        expected = scene.copies
    chain = core.SceneIndexChain(stage)
    plan = core.plan(chain.capture(Usd.TimeCode(0.0)), SETTINGS, CONTEXT)
    chain.release()
    stage_ref = weakref.ref(stage)
    del stage
    gc.collect()
    assert stage_ref() is None
    binding_id = bindings.create_binding(bpy.data.scenes["Scene"]).binding_id
    work = preparation_resources.new_preparation_resources(binding_id, OriginatingOperation.SYNCHRONIZE)
    application.prepare(plan, range(plan.copy_count), Manifest({}), work)
    roles = [e.role for e in work.manifest_entries.values()]
    assert roles.count(RepresentationRole.OBJECT) == len(expected)
    assert roles.count(RepresentationRole.BOUNDS_MESH) == sum(c.has_bounds for c in expected)
    assert roles.count(RepresentationRole.SHEAR_PARENT) == sum(c.sheared for c in expected)
    assert not preparation_resources.dispose(work)


def test_preparing_some_copies_makes_only_their_partitions(bindings: Bindings, tmp_path: Path) -> None:
    # Each copy's partition is made on its own, so preparing some copies makes theirs, in the order asked, and
    # preparing the rest makes the others: together, what preparing every copy makes.
    with incremental.no_op_refresh(tmp_path) as scene:
        chain = core.SceneIndexChain(scene.stage)
        plan = core.plan(chain.capture(Usd.TimeCode(0.0)), SETTINGS, CONTEXT)
        chain.release()
    binding_id = bindings.create_binding(bpy.data.scenes["Scene"]).binding_id
    sources = [e.source_path for e in plan.correspondence]
    sheared = sources.index(next(c.source_path for c in scene.copies if c.sheared))
    marker = sources.index(next(c.source_path for c in scene.copies if c.placeholder and not c.has_bounds))
    asked = [marker, sheared]
    rest = [i for i in range(plan.copy_count) if i not in asked]

    def prepared(copy_indices: list[int]) -> list[tuple[str, RepresentationRole]]:
        work = preparation_resources.new_preparation_resources(binding_id, OriginatingOperation.SYNCHRONIZE)
        application.prepare(plan, copy_indices, Manifest({}), work)
        made = [(e.source_entity_paths[0], e.role) for e in work.manifest_entries.values()]
        assert not preparation_resources.dispose(work)
        return made

    some = prepared(asked)
    assert some == [
        (sources[marker], RepresentationRole.OBJECT),
        (sources[sheared], RepresentationRole.BOUNDS_MESH),
        (sources[sheared], RepresentationRole.OBJECT),
        (sources[sheared], RepresentationRole.SHEAR_PARENT),
    ]
    assert sorted(some + prepared(rest)) == sorted(prepared(list(range(plan.copy_count))))
