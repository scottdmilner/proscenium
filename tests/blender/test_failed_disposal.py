"""Preparation failing and its disposal failing too, through synchronizations (M5 plan, D8).

On F-PREPARATION-CLEANUP-FAILURE (fixtures/transaction.py): preparation fails once four resources are made, and
disposal then fails for the first object and bounds mesh made. Failures are injected by patching the steps' module
functions, for one synchronization at a time, so src/ has no hooks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest

from fixtures import transaction
from proscenium.binding import runtime
from proscenium.binding.persistence import binding_state, configs, records
from proscenium.binding.persistence.ledgers import LedgerEntry, OriginatingOperation
from proscenium.binding.persistence.records import Loaded
from proscenium.binding.results import DiagnosticCode, Result, ResultState
from proscenium.binding.runtime import ownership_index, pending_cleanup
from support.blend import save_and_reopen
from support.destinations import destination

from .published import datablocks, published_generation
from .transaction_failures import failing_preparation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from fixtures.transaction import PreparationCleanupFailureScene
    from proscenium.api.bindings import BindingHandle, Bindings


def _binding(bindings: Bindings, scene: PreparationCleanupFailureScene) -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
    assert handle.attach(scene.caller).state is ResultState.SUCCESS
    return handle


def _destination() -> bpy.types.Collection:
    return bpy.data.collections["Shot"]


def _ledger() -> dict[str, LedgerEntry]:
    ledger = pending_cleanup.ledger()
    assert not isinstance(ledger, records.RefusedRecord)
    return {} if ledger is None else dict(ledger.record.entries)


def _published(handle: BindingHandle) -> dict[str, Any]:
    return published_generation(handle.binding_id, _destination())


def _check_failed(handle: BindingHandle, result: Result, scene: PreparationCleanupFailureScene) -> None:
    """The attempt is fatal, reporting the preparation failure and a pending-cleanup diagnostic per leftover."""
    assert result.state is scene.outcome
    assert [d.code for d in result.diagnostics] == [
        DiagnosticCode.PREPARATION_FAILED,
        *[DiagnosticCode.DISPOSAL_FAILED] * len(scene.failed_disposals),
    ]
    attempt = binding_state.read_last_attempt(destination(handle))
    assert isinstance(attempt, Loaded) and attempt.record.diagnostics == result.diagnostics


def _check_leftovers(handle: BindingHandle, result: Result, leftovers: set[bpy.types.ID]) -> None:
    """The leftovers are the ledger's, with their evidence and diagnostics, inactive and noncanonical."""
    ledger = {k: e for k, e in _ledger().items() if e.datablock in leftovers}
    assert {e.datablock for e in ledger.values()} == leftovers
    for ledger_key, entry in ledger.items():
        assert (entry.binding_id, entry.operation) == (handle.binding_id, OriginatingOperation.SYNCHRONIZE)
        assert entry.diagnostic in result.diagnostics
        assert (entry.diagnostic.resource, entry.diagnostic.role) == (ledger_key, entry.role)
        assert entry.datablock is not None and ownership_index.ownership(entry.datablock).claims == ()
    assert all(not d.users_collection for d in leftovers if isinstance(d, bpy.types.Object))  # in no scene
    assert set(result.cleanup_status) >= {e.diagnostic for e in ledger.values()}


def test_a_failed_first_synchronization_leaves_only_tracked_leftovers(bindings: Bindings, tmp_path: Path) -> None:
    # TXN-03, TXN-04, TXN-10, STATE-04, API-13 on F-PREPARATION-CLEANUP-FAILURE "first": nothing is published, and
    # the file holds what it did before plus exactly the ledger's leftovers.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        nothing, before = _published(handle), datablocks()
        result, leftovers = failing_preparation(handle, scene, 0)
        _check_failed(handle, result, scene)
        _check_leftovers(handle, result, leftovers)
        assert datablocks() - before == {(type(d).__name__, d.session_uid) for d in leftovers}
        assert {e.datablock for e in _ledger().values()} == leftovers
        assert _published(handle) == nothing
        assert result.cleanup_status == tuple(e.diagnostic for _, e in sorted(_ledger().items()))


def test_a_failed_replacement_leaves_the_published_generation_alone(bindings: Bindings, tmp_path: Path) -> None:
    # TXN-03, TXN-05, TXN-09, TXN-10, DIAG-05 on F-PREPARATION-CLEANUP-FAILURE "replace": the published generation's
    # records and content keep their values, and none of its resources is in the ledger or disposed of.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        assert handle.synchronize(0).state is ResultState.SUCCESS
        published = _published(handle)
        manifest = ownership_index.manifest(handle.binding_id)
        assert isinstance(manifest, Loaded)
        named = {e.datablock for e in manifest.record.entries.values()}
        result, leftovers = failing_preparation(handle, scene, 10)
        _check_failed(handle, result, scene)
        _check_leftovers(handle, result, leftovers)
        assert _published(handle) == published
        assert ownership_index.manifest(handle.binding_id) == manifest
        assert named <= {*bpy.data.objects, *bpy.data.meshes}  # none disposed of
        assert named.isdisjoint(e.datablock for e in _ledger().values())
        assert leftovers.isdisjoint(_destination().objects)


def test_repeated_failures_add_only_tracked_leftovers_each_reported_once(bindings: Bindings, tmp_path: Path) -> None:
    # DIAG-03, DIAG-05, DIAG-06 on F-PREPARATION-CLEANUP-FAILURE "repeat": the earlier leftovers keep their entries
    # and diagnostics; this attempt's are its own, once each, and the cleanup status lists all of them once.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        earlier, _ = failing_preparation(handle, scene, 0)
        before = _ledger()
        again, leftovers = failing_preparation(handle, scene, 0)
        _check_failed(handle, again, scene)
        after = _ledger()
        assert {k: after[k] for k in before} == before
        assert len(after) == len(before) + len(leftovers)
        assert set(again.diagnostics[1:]).isdisjoint(earlier.diagnostics)
        assert len(again.cleanup_status) == len(after)
        assert set(again.cleanup_status) == {e.diagnostic for e in after.values()}


def test_a_later_success_keeps_the_earlier_pending_work(bindings: Bindings, tmp_path: Path) -> None:
    # DIAG-05, DIAG-15 on F-PREPARATION-CLEANUP-FAILURE "later-success": it succeeds, with the earlier leftovers in
    # its cleanup status and not among its own diagnostics, and the ledger keeps them.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        failing_preparation(handle, scene, 0)
        before = _ledger()
        result = handle.synchronize(0)
        assert (result.state, result.diagnostics) == (ResultState.SUCCESS, ())
        assert result.cleanup_status == tuple(e.diagnostic for _, e in sorted(before.items()))
        assert _ledger() == before


def test_a_disposal_the_ledger_cant_record_raises(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # API-05: a ledger write failing as disposal records its leftovers is a defect, and raises; the staging collection
    # still goes, and the published generation is as it was (here, none).
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        nothing = _published(handle)
        write = pending_cleanup.set_ledger_entries

        def failing(changed: Mapping[str, LedgerEntry], removed: Sequence[str] = ()) -> None:
            if changed:  # disposal's record of its leftovers, the one write here
                raise RuntimeError("injected ledger failure")
            write(changed, removed)

        monkeypatch.setattr(pending_cleanup, "set_ledger_entries", failing)
        with pytest.raises(RuntimeError, match="injected ledger failure"):
            failing_preparation(handle, scene, 0)
        assert [c.name for c in bpy.data.collections] == ["Shot"]  # the staging collection is gone
        assert _published(handle) == nothing


def test_removing_the_destination_leaves_the_pending_cleanup(bindings: Bindings, tmp_path: Path) -> None:
    # DEST-09 on F-PREPARATION-CLEANUP-FAILURE "removed-destination": the binding goes with its destination, but
    # its index entry, naming no collection, and its leftovers and their ledger entries stay, through save and reopen.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        failing_preparation(handle, scene, 0)
        named = {k: (e.binding_id, e.role, e.datablock and e.datablock.name) for k, e in _ledger().items()}
        assert named
        bpy.data.collections.remove(_destination())
        for check in range(2):
            if check:
                save_and_reopen(tmp_path / "removed.blend")
            assert runtime.binding_configs.find_binding(handle.binding_id) is None
            assert {k: (e.binding_id, e.role, e.datablock and e.datablock.name) for k, e in _ledger().items()} == named
            [text] = configs.index_texts()
            index = records.read(text, configs.INDEX_KEY, configs.INDEX)
            assert isinstance(index, Loaded) and index.record.destinations == {handle.binding_id: None}
