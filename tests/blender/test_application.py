"""M5's stub application layer: preparing a plan's placeholders apart from the display (M5 plan, D3 and D4).

Plans come from the core on the transaction scenes; expected values come from how the scene is built
(fixtures/transaction.py). Each preparation is a binding's, and the ledger tracks what it makes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest
from pxr import Usd

from fixtures import transaction
from fixtures.transaction import EXTENT, ROLES_PER_PLACEHOLDER, translation
from proscenium.binding import runtime
from proscenium.binding.persistence import (
    CopyResourceIdentity,
    Manifest,
    OriginatingOperation,
    RepresentationRole,
    RetryStatus,
)
from proscenium.binding.results import DiagnosticCode
from proscenium.binding.source_access import PayloadPolicy
from proscenium.core import _core
from proscenium.synchronization import application, prepared_work
from support.blend import save_and_reopen
from support.usd import open_fresh

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.api.bindings import Bindings
    from proscenium.binding.persistence import LedgerEntry
    from proscenium.binding.source_access import BindingId
    from proscenium.synchronization.prepared_work import PreparedWork

CONTEXT = _core.PlanningContext(unit_scale=1.0, representation_version=1)


def _plan(stage: Usd.Stage, time_code: float) -> _core.Plan:
    return _core.plan(_core.SceneIndexChain(stage).capture(Usd.TimeCode(time_code)), CONTEXT)


def _binding(bindings: Bindings) -> BindingId:
    return bindings.create_binding(bpy.data.scenes["Scene"]).binding_id


def _work(binding_id: BindingId) -> PreparedWork:
    return prepared_work.new_prepared_work(binding_id, OriginatingOperation.SYNCHRONIZE)


def _prepared(binding_id: BindingId, plan: _core.Plan, published: Manifest | None = None) -> PreparedWork:
    work = _work(binding_id)
    application.prepare(plan, published or Manifest({}), work)
    return work


def _ledger() -> dict[str, LedgerEntry]:
    ledger = runtime.ledger()
    return {} if ledger is None else dict(ledger.record.entries)  # ty: ignore[unresolved-attribute] - not refused


def _datablocks() -> set[bpy.types.ID]:
    return {*bpy.data.objects, *bpy.data.meshes, *bpy.data.collections}


def _values(objects: list[bpy.types.Object]) -> list[object]:
    """What a published object shows: its placement, its mesh's vertices, and its collections."""
    return [
        (
            obj.name,
            [row[:] for row in obj.matrix_world],
            [v.co[:] for v in obj.data.vertices],  # ty: ignore[unresolved-attribute] - a mesh object's
            sorted(c.name for c in obj.users_collection),
        )
        for obj in objects
    ]


def _records() -> list[object]:
    """The records on the scene and the collections, as stored."""
    return [{k: v.to_dict() for k, v in id_.items()} for id_ in (*bpy.data.scenes, *bpy.data.collections)]


def test_a_placeholder_per_partition_in_no_scene(bindings: Bindings, tmp_path: Path) -> None:
    # TXN-05: an object drawing its bounds, and its bounds mesh, per drawn gprim, linked only in the staging collection.
    with transaction.retirement_failure(tmp_path) as scene:
        work = _prepared(_binding(bindings), _plan(scene.caller, 0.0))
        objects = list(work.staging.objects)
        assert len(objects) == len(transaction.DRAWN[PayloadPolicy.LOAD_ALL])
        assert not any(work.staging in s.collection.children_recursive for s in bpy.data.scenes)
        assert all(obj.users_collection == (work.staging,) for obj in objects)
        low, high = EXTENT
        corners = {(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])}
        for obj in objects:
            source = work.entries[_key(work, obj)].covers[0]
            assert obj.display_type == "BOUNDS"
            assert obj.matrix_world.translation[:] == pytest.approx(translation(source, 0.0))
            assert {v.co[:] for v in obj.data.vertices} == corners  # ty: ignore[unresolved-attribute]


def test_its_entries_are_the_plans_resources(bindings: Bindings, tmp_path: Path) -> None:
    # Each prepared datablock has the entry a publication writes: its role, the source it covers, its place, and the
    # object using its own bounds mesh.
    with transaction.retirement_failure(tmp_path) as scene:
        work = _prepared(_binding(bindings), _plan(scene.caller, 0.0))
        assert len(work.entries) == transaction.resource_count(PayloadPolicy.LOAD_ALL)
        assert work.datablocks.keys() == work.entries.keys()
        for key, entry in work.entries.items():
            assert entry.datablock == work.datablocks[key]
            assert entry.role in ROLES_PER_PLACEHOLDER
            if entry.role is RepresentationRole.OBJECT:
                [used] = entry.uses
                assert entry.datablock.data == work.datablocks[used]  # ty: ignore[unresolved-attribute]
                bounds_mesh = CopyResourceIdentity(RepresentationRole.BOUNDS_MESH, entry.covers[0], 0)
                assert work.entries[used].identity == bounds_mesh
            assert entry.identity == CopyResourceIdentity(entry.role, entry.covers[0], 0)
        Manifest(work.entries)  # a whole manifest


def test_each_prepared_resource_is_tracked(bindings: Bindings, tmp_path: Path) -> None:
    # STATE-04: the ledger holds each with its ownership evidence, operation, and retry status, apart from the binding's
    # other records, which tracking leaves unchanged.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        before = _records()
        work = _prepared(binding_id, _plan(scene.caller, 0.0))
        assert _ledger() == work.tracked
        assert {(e.entry_key, e.role, e.datablock) for e in work.tracked.values()} == {
            (key, entry.role, entry.datablock) for key, entry in work.entries.items()
        }
        assert {(e.binding_id, e.operation, e.status, e.diagnostic) for e in work.tracked.values()} == {
            (binding_id, OriginatingOperation.SYNCHRONIZE, RetryStatus.PREPARED, None)
        }
        bpy.data.batch_remove([work.staging])  # which holds no records
        assert _records() == before


# Preparation's fallible steps after a resource is made, by the function each runs: its call-th call fails.
_STEPS = [("_corners", call) for call in range(1, 5)] + [("_world", call) for call in range(1, 5)]


@pytest.mark.parametrize(("step", "call"), _STEPS)
def test_a_failure_after_a_resource_is_made_finds_it_tracked(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str, call: int
) -> None:
    # TXN-08 on F-PREPARATION-CLEANUP-FAILURE: every resource made before the failure is in the ledger, and
    # disposing of the work leaves the file as before.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        plan = _plan(scene.caller, 0.0)
        _fail_on_call(monkeypatch, step, call)
        before = _datablocks()
        work = _work(binding_id)
        with pytest.raises(RuntimeError, match="injected"):
            application.prepare(plan, Manifest({}), work)
        made = _datablocks() - before - {work.staging}
        assert made == set(work.datablocks.values())
        assert len(made) == 2 * call - (step == "_corners")  # a placeholder's mesh is made before its corners
        assert {e.datablock for e in _ledger().values()} == made
        assert prepared_work.dispose(work) == ()
        assert _datablocks() == before
        assert _ledger() == {}


def test_a_failure_writing_the_ledger_leaves_the_untracked_resource_to_dispose_of(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The resource whose tracking failed is held, though not in the ledger, so disposal still removes it.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        plan = _plan(scene.caller, 0.0)
        before = _datablocks()
        work = _work(binding_id)
        write = runtime.set_ledger_entries
        calls = []

        def failing(*args: object) -> None:
            calls.append(args)
            if len(calls) == 3:
                raise RuntimeError("injected")
            write(*args)  # ty: ignore[invalid-argument-type]

        monkeypatch.setattr(runtime, "set_ledger_entries", failing)
        with pytest.raises(RuntimeError, match="injected"):
            application.prepare(plan, Manifest({}), work)
        assert len(work.datablocks) == 3
        assert len(_ledger()) == 2
        monkeypatch.setattr(runtime, "set_ledger_entries", write)
        assert prepared_work.dispose(work) == ()
        assert _datablocks() == before


def test_a_replacement_takes_the_published_keys_and_changes_nothing_published(
    bindings: Bindings, tmp_path: Path
) -> None:
    # ROLE-05: prepared resources with the published ones' identities take their keys. TXN-05: preparing them
    # changes nothing the published generation reaches. TXN-09: none of the published resources is tracked.
    with transaction.retirement_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        first, second = scene.time_codes
        published = _prepared(binding_id, _plan(scene.caller, first))
        objects = _publish(published)
        before = _values(objects)
        replacement = _prepared(binding_id, _plan(scene.caller, second), Manifest(published.entries))
        assert replacement.entries.keys() == published.entries.keys()
        assert set(replacement.datablocks.values()).isdisjoint(published.datablocks.values())
        assert _values(objects) == before
        assert {e.datablock for e in _ledger().values()} == set(replacement.datablocks.values())
        mover = next(o for o in replacement.staging.objects if "Mover" in o.name)
        assert mover.matrix_world.translation[:] == pytest.approx(translation("/World/Mover", second))


def test_only_the_same_identity_takes_a_published_key(bindings: Bindings, tmp_path: Path) -> None:
    # Planned without the payloaded gprim, the others take their published keys, and its entries' go unused.
    with transaction.retirement_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        published = _prepared(binding_id, _plan(scene.caller, 0.0))
        unloaded = _plan(open_fresh(scene.root, PayloadPolicy.LOAD_NONE.load_set), 0.0)  # without /World/Payloaded
        drawn = transaction.DRAWN[PayloadPolicy.LOAD_NONE]
        kept = {key for key, entry in published.entries.items() if entry.covers[0] in drawn}
        replacement = _prepared(binding_id, unloaded, Manifest(published.entries))
        assert replacement.entries.keys() == kept


def test_dispose_removes_what_was_prepared_and_resolves_its_tracking(bindings: Bindings, tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        before = _datablocks()
        work = _prepared(binding_id, _plan(scene.caller, 0.0))
        assert prepared_work.dispose(work) == ()
        assert _datablocks() == before
        assert (work.datablocks, work.entries, work.tracked) == ({}, {}, {})
        assert _ledger() == {}


def test_a_failed_disposal_leaves_tracked_inactive_leftovers(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # F-PREPARATION-CLEANUP-FAILURE: preparation fails once four resources are made, and disposal fails for an object
    # and a bounds mesh. They stay, linked in no collection, each retryable in the ledger with a cleanup diagnostic
    # naming its ledger key; the rest are removed and resolved.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        plan = _plan(scene.caller, 0.0)
        _fail_on_call(monkeypatch, "_world", 2)
        before = _datablocks()
        work = _work(binding_id)
        with pytest.raises(RuntimeError, match="injected"):
            application.prepare(plan, Manifest({}), work)
        assert len(work.datablocks) == scene.prepared_before_failure
        failing = _fail_disposal(monkeypatch, work, scene.failed_disposals)
        diagnostics = prepared_work.dispose(work)
        assert _datablocks() - before == failing
        assert all(not d.users_collection for d in failing if isinstance(d, bpy.types.Object))
        ledger = _ledger()
        assert {e.datablock for e in ledger.values()} == failing
        assert all(e.status is RetryStatus.RETRYABLE for e in ledger.values())
        assert {e.diagnostic for e in ledger.values()} == set(diagnostics)
        assert {(d.code, d.binding_id, d.resource, d.role) for d in diagnostics} == {
            (DiagnosticCode.DISPOSAL_FAILED, binding_id, ledger_key, entry.role) for ledger_key, entry in ledger.items()
        }


def test_a_leftover_survives_save_and_reopen_through_its_pointer(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The ledger's pointer is the leftover's only user, so it's saved, and found again after reopening.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        work = _prepared(_binding(bindings), _plan(scene.caller, 0.0))
        [leftover] = _fail_disposal(monkeypatch, work, (RepresentationRole.BOUNDS_MESH,))
        name = leftover.name
        [diagnostic] = prepared_work.dispose(work)
        save_and_reopen(tmp_path / "leftover.blend")
        [(ledger_key, entry)] = _ledger().items()
        assert entry.datablock == bpy.data.meshes[name]
        assert (ledger_key, entry.diagnostic) == (diagnostic.resource, diagnostic)


def _publish(work: PreparedWork) -> list[bpy.types.Object]:
    """Link work's objects into a destination and resolve their tracking, as a publication does; the objects."""
    destination = bpy.data.collections.new("Shot")
    bpy.data.scenes["Scene"].collection.children.link(destination)
    objects = list(work.staging.objects)
    for obj in objects:
        destination.objects.link(obj)
        work.staging.objects.unlink(obj)
    runtime.set_ledger_entries({}, list(work.tracked))
    return objects


def _fail_disposal(monkeypatch: pytest.MonkeyPatch, work: PreparedWork, roles: tuple[str, ...]) -> set[bpy.types.ID]:
    """Make disposal fail for the first tracked datablock of each role; those datablocks."""
    failing = {next(e.datablock for e in work.tracked.values() if e.role == role) for role in roles}
    remove = prepared_work._remove  # noqa: SLF001

    def failing_remove(datablock: bpy.types.ID) -> None:
        if datablock in failing:
            raise RuntimeError("disposal injected")
        remove(datablock)

    monkeypatch.setattr(prepared_work, "_remove", failing_remove)
    return {d for d in failing if d is not None}


def _fail_on_call(monkeypatch: pytest.MonkeyPatch, step: str, call: int) -> None:
    """Make application's function step raise on its call-th call."""
    original = getattr(application, step)
    calls = []

    def failing(*args: object) -> object:
        calls.append(args)
        if len(calls) == call:
            raise RuntimeError("injected")
        return original(*args)

    monkeypatch.setattr(application, step, failing)


def _key(work: PreparedWork, datablock: bpy.types.ID) -> str:
    [key] = [k for k, d in work.datablocks.items() if d == datablock]
    return key
