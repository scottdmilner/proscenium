"""Retrying pending cleanup explicitly (M5 plan, D9; lifecycle.md#pending-cleanup).

On F-PREPARATION-CLEANUP-FAILURE (fixtures/transaction.py), whose failed synchronization leaves an object and a bounds
mesh pending. Failures are injected by patching the removal module's function, so src/ has no hooks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from fixtures import records as record_fixtures
from fixtures import transaction
from proscenium.binding.persistence import configs, ledgers, records
from proscenium.binding.results import DiagnosticCode, ResultState
from proscenium.binding.runtime import pending_cleanup, state
from proscenium.synchronization import removal
from support.blend import save_and_reopen

from .transaction_failures import failing_preparation

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import pytest

    from fixtures.transaction import PreparationCleanupFailureScene
    from proscenium.api.bindings import BindingHandle, Bindings
    from proscenium.binding.persistence.ledgers import LedgerEntry


def _binding(bindings: Bindings, scene: PreparationCleanupFailureScene, name: str = "Shot") -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name=name)
    assert handle.attach(scene.caller).state is ResultState.SUCCESS
    return handle


def _ledger() -> dict[str, LedgerEntry]:
    ledger = pending_cleanup.ledger()
    assert not isinstance(ledger, records.RefusedRecord)
    return {} if ledger is None else dict(ledger.record.entries)


def _names() -> set[tuple[str, str]]:
    return {("object", o.name) for o in bpy.data.objects} | {("mesh", m.name) for m in bpy.data.meshes}


def _by_name(ledger: dict[str, LedgerEntry]) -> dict[str, tuple[object, ...]]:
    """The ledger's entries with their pointers as names: references don't survive a reopen."""
    return {
        k: (e.binding_id, e.entry_key, e.role, e.datablock and e.datablock.name, e.operation, e.diagnostic)
        for k, e in ledger.items()
    }


def _fail_removing(monkeypatch: pytest.MonkeyPatch, failing: set[bpy.types.ID]) -> None:
    """Make removing one of failing fail, or a call with one; by datablock, as an object and its mesh share a name."""
    remove = removal._batch_remove  # noqa: SLF001 - the step's module function

    def failing_remove(datablocks: Sequence[bpy.types.ID]) -> None:
        if any(d in failing for d in datablocks):
            raise RuntimeError("injected failure")
        remove(datablocks)

    monkeypatch.setattr(removal, "_batch_remove", failing_remove)


def test_a_retry_after_reopening_resolves_it_all(bindings: Bindings, tmp_path: Path) -> None:
    # REOPEN-01, PEND-01, PEND-03, PEND-04, DIAG-08, STAB-03 on F-PREPARATION-CLEANUP-FAILURE "retry-after-reopen":
    # reopening restores the ledger and retries nothing; a retry, with the binding unattached, finds each leftover by
    # its saved pointer, disposes of it, and leaves no entry, diagnostic, or resource of the failed attempt.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        baseline = _names()
        _, leftovers = failing_preparation(handle, scene, 0)
        saved = _by_name(_ledger())
        names = {d.name for d in leftovers}
        save_and_reopen(tmp_path / "pending.blend")
        assert _by_name(_ledger()) == saved
        assert names <= {name for _, name in _names()}  # no cleanup ran
        assert handle.live_stage() is None  # unattached: the retry needs no USD
        result = handle.retry_cleanup()
        assert (result.state, result.diagnostics, result.cleanup_status) == (ResultState.SUCCESS, (), ())
        assert _ledger() == {}
        assert _names() == baseline


def test_a_leftover_something_else_uses_is_released_intact(bindings: Bindings, tmp_path: Path) -> None:
    # PEND-02, STAB-04 on F-PREPARATION-CLEANUP-FAILURE "unmanaged-user": an unmanaged object given the leftover bounds
    # mesh keeps it, released from the ledger, while the leftover object is disposed of.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        _, leftovers = failing_preparation(handle, scene, 0)
        [mesh] = (d for d in leftovers if isinstance(d, bpy.types.Mesh))
        [leftover] = (d.name for d in leftovers if isinstance(d, bpy.types.Object))
        mine = bpy.data.objects.new("Mine", mesh)
        bpy.data.scenes["Scene"].collection.objects.link(mine)
        assert handle.retry_cleanup().state is ResultState.SUCCESS
        assert mine.data == mesh and mesh.name in bpy.data.meshes
        assert leftover not in bpy.data.objects
        assert _ledger() == {}


def test_a_retry_that_resolves_nothing_fails(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Cleanup that commits nothing fails (lifecycle.md#lifecycle-failure-safety); each leftover stays retryable with a
    # fresh diagnostic naming its ledger key.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        failed, leftovers = failing_preparation(handle, scene, 0)
        before = _ledger()
        _fail_removing(monkeypatch, leftovers)
        result = handle.retry_cleanup()
        assert result.state is ResultState.FATAL_FAILURE
        assert [d.code for d in result.diagnostics] == [DiagnosticCode.CLEANUP_FAILED] + [
            DiagnosticCode.DISPOSAL_FAILED
        ] * len(leftovers)
        after = _ledger()
        assert after.keys() == before.keys()
        assert {e.diagnostic for e in after.values()} == set(result.diagnostics[1:])
        assert set(result.cleanup_status) == set(result.diagnostics[1:])
        assert set(result.diagnostics[1:]).isdisjoint(failed.diagnostics)  # fresh, not the attempt's


def test_a_retry_that_resolves_some_completes_with_issues(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The leftover object is disposed of and the mesh it used isn't: the progress is committed, and the rest reported.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        _, leftovers = failing_preparation(handle, scene, 0)
        [mesh] = (d for d in leftovers if isinstance(d, bpy.types.Mesh))
        _fail_removing(monkeypatch, {mesh})
        result = handle.retry_cleanup()
        assert result.state is ResultState.COMPLETED_WITH_ISSUES
        [diagnostic] = result.diagnostics
        [(ledger_key, entry)] = _ledger().items()
        assert (entry.datablock, entry.diagnostic, diagnostic.resource) == (mesh, diagnostic, ledger_key)


def test_a_retry_resolves_only_its_bindings_leftovers(bindings: Bindings, tmp_path: Path) -> None:
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle, other = _binding(bindings, scene), _binding(bindings, scene, "Other")
        failing_preparation(handle, scene, 0)
        failing_preparation(other, scene, 0)
        others = {k: e for k, e in _ledger().items() if e.binding_id == other.binding_id}
        assert handle.retry_cleanup().state is ResultState.SUCCESS
        assert _ledger() == others
        assert len(other.retry_cleanup().cleanup_status) == 0
        assert _ledger() == {}


def test_a_ledger_that_cant_be_read_refuses_and_disposes_of_nothing(bindings: Bindings, tmp_path: Path) -> None:
    # SCHEMA-06 on F-SCHEMA-VERSIONS' "unsupported-ledger": refused with a diagnostic naming the record.
    with (
        transaction.preparation_cleanup_failure(tmp_path) as scene,
        record_fixtures.schema_versions(tmp_path / "versions") as versions,
    ):
        handle = _binding(bindings, scene)
        _, leftovers = failing_preparation(handle, scene, 0)
        names = {d.name for d in leftovers}
        [text] = configs.index_texts()
        text[records.NAMESPACE][ledgers.LEDGER_KEY] = versions.ledgers["newer"]
        state.invalidate()  # the record changed behind the state, as a load or undo changes it
        result = handle.retry_cleanup()
        assert result.state is ResultState.FATAL_FAILURE
        [diagnostic] = result.diagnostics
        assert diagnostic.code is DiagnosticCode.UNSUPPORTED_RECORD and "ledger" in diagnostic.message
        assert names <= {name for _, name in _names()}
