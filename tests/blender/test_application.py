"""M5's stub application layer: preparing a plan's drawn copies apart from the display (M5 plan, D3 and D4).

Plans come from the core on the transaction scenes; expected values come from how the scene is built
(fixtures/transaction.py). Each preparation is a binding's, and its prepared work holds what it makes; only what
disposal fails to remove enters the ledger.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest
from mathutils import Matrix
from pxr import Usd

from fixtures import evaluation, transaction
from fixtures.transaction import EXTENT, ROLES_PER_PLACEHOLDER, translation
from proscenium.binding import runtime
from proscenium.binding.persistence.ledgers import OriginatingOperation
from proscenium.binding.persistence.manifests import CopyResourceIdentity, Manifest, RepresentationRole
from proscenium.binding.results import DiagnosticCode
from proscenium.binding.source_access.stages import PayloadPolicy
from proscenium.core import _core
from proscenium.synchronization import application, prepared_work, removal
from support.blend import save_and_reopen
from support.usd import open_fresh

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from proscenium.api.bindings import Bindings
    from proscenium.binding.persistence.ledgers import LedgerEntry
    from proscenium.binding.source_access.identifiers import BindingId
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
    ledger = runtime.pending_cleanup.ledger()
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


def test_a_drawn_copy_per_partition_in_no_scene(bindings: Bindings, tmp_path: Path) -> None:
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


def test_world_transforms_cross_in_blenders_layout(bindings: Bindings, tmp_path: Path) -> None:
    # The plan's copy_worlds holds Blender's layout, so foreach_set writes it as it stands, and the stub's objects get
    # the same. Expected values are UsdGeom's, transposed, on F-TRANSFORMS' rotated, scaled, and mirrored copies; a
    # sheared one needs a shear parent (C4).
    with evaluation.transforms(tmp_path) as scene:
        plan = _plan(scene.stage, 0.0)
        expected = {
            p: Matrix([[w[r, c] for c in range(4)] for r in range(4)]).transposed() for p, w in scene.world.items()
        }
        sources = [c.source for c in plan.correspondence]
        made = [bpy.data.objects.new(f"copy-{copy:04}", None) for copy in range(plan.copy_count)]
        assert list(bpy.data.objects) == made  # in copy order, so foreach_set's buffer lines up
        bpy.data.objects.foreach_set("matrix_world", plan.copy_worlds)
        work = _prepared(_binding(bindings), plan)
        prepared = {work.entries[_key(work, obj)].covers[0]: obj for obj in work.staging.objects}
        for source, obj in zip(sources, made, strict=True):
            if source in scene.sheared:
                continue
            assert _close(obj.matrix_world, expected[source]), source
            assert _close(prepared[source].matrix_world, expected[source]), source


def _close(shown: Matrix, expected: Matrix) -> bool:
    return all(abs(shown[r][c] - expected[r][c]) <= 1e-5 for r in range(4) for c in range(4))


def test_each_prepared_resource_is_held(bindings: Bindings, tmp_path: Path) -> None:
    # TXN-08: the prepared work holds each with its entry key and role, and preparing writes no record, the ledger's
    # included (STATE-04).
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        before = _records()
        work = _prepared(binding_id, _plan(scene.caller, 0.0))
        assert {(key, work.roles[key], d) for key, d in work.datablocks.items()} == {
            (key, entry.role, entry.datablock) for key, entry in work.entries.items()
        }
        assert _ledger() == {}
        bpy.data.batch_remove([work.staging])  # which holds no records
        assert _records() == before


# Preparation's fallible steps after a resource is made, by the function each runs: its call-th call fails.
_STEPS = [("_corners", call) for call in range(1, 5)] + [("_world", call) for call in range(1, 5)]


@pytest.mark.parametrize(("step", "call"), _STEPS)
def test_a_failure_after_a_resource_is_made_finds_it_held(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str, call: int
) -> None:
    # TXN-08 on F-PREPARATION-CLEANUP-FAILURE: every resource made before the failure is held, and disposing of the
    # work leaves the file as before, writing no ledger entry.
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
        assert prepared_work.dispose(work) == ()
        assert _datablocks() == before
        assert _ledger() == {}


def test_a_replacement_takes_the_published_keys_and_changes_nothing_published(
    bindings: Bindings, tmp_path: Path
) -> None:
    # ROLE-05: prepared resources with the published ones' identities take their keys. TXN-05: preparing them
    # changes nothing the published generation reaches. TXN-09: none of the published resources is held.
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
        assert _ledger() == {}
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


def test_dispose_removes_what_was_prepared_and_writes_no_ledger_entry(bindings: Bindings, tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        binding_id = _binding(bindings)
        before = _datablocks()
        work = _prepared(binding_id, _plan(scene.caller, 0.0))
        assert prepared_work.dispose(work) == ()
        assert _datablocks() == before
        assert (work.datablocks, work.roles, work.entries) == ({}, {}, {})
        assert _ledger() == {}


def test_a_failed_disposal_leaves_tracked_inactive_leftovers(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # F-PREPARATION-CLEANUP-FAILURE: preparation fails once four resources are made, and disposal fails for an object
    # and a bounds mesh. They stay, linked in no collection, each retryable in the ledger with a cleanup diagnostic
    # naming its ledger key; the rest are removed, with no entry.
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
    """Link work's objects into a destination, as a publication does; the objects."""
    destination = bpy.data.collections.new("Shot")
    bpy.data.scenes["Scene"].collection.children.link(destination)
    objects = list(work.staging.objects)
    for obj in objects:
        destination.objects.link(obj)
        work.staging.objects.unlink(obj)
    return objects


def _fail_disposal(monkeypatch: pytest.MonkeyPatch, work: PreparedWork, roles: tuple[str, ...]) -> set[bpy.types.ID]:
    """Make disposal fail for the first held datablock of each role; those datablocks."""
    failing = {next(d for key, d in work.datablocks.items() if work.roles[key] == role) for role in roles}
    remove = removal._batch_remove  # noqa: SLF001

    def failing_remove(datablocks: Sequence[bpy.types.ID]) -> None:
        if any(d in failing for d in datablocks):  # a call removing one fails, the batch's included
            raise RuntimeError("disposal injected")
        remove(datablocks)

    monkeypatch.setattr(removal, "_batch_remove", failing_remove)
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
