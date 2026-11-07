"""Retirement: the resources a publication made obsolete, removed or left pending (M5 plan, D7).

On F-RETIREMENT-FAILURE (fixtures/transaction.py). A failed removal is injected by patching the removal module's
function, so src/ has no hooks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import transaction
from proscenium.binding.persistence import binding_state, manifests, records
from proscenium.binding.persistence.records import Loaded
from proscenium.binding.results import DiagnosticCategory, DiagnosticCode, ResultState
from proscenium.binding.runtime import ownership, pending_cleanup
from proscenium.binding.source_access.stages import PayloadPolicy
from proscenium.synchronization import removal
from support.destinations import destination

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from fixtures.transaction import RetirementFailureScene
    from proscenium.api.bindings import BindingHandle, Bindings
    from proscenium.binding.persistence.ledgers import LedgerEntry

FAILING = "Still"  # the placeholder whose object and bounds mesh can't be retired: /World/Still's


def _binding(bindings: Bindings, scene: RetirementFailureScene) -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
    assert handle.attach(scene.caller).state is ResultState.SUCCESS
    return handle


def _manifest(handle: BindingHandle) -> manifests.Manifest:
    manifest = ownership.manifest(handle.binding_id)
    assert isinstance(manifest, Loaded)
    return manifest.record


def _ledger() -> dict[str, LedgerEntry]:
    ledger = pending_cleanup.ledger()
    assert not isinstance(ledger, records.RefusedRecord)
    return {} if ledger is None else dict(ledger.record.entries)


def _fail_retirement(monkeypatch: pytest.MonkeyPatch) -> None:
    """Removing FAILING's object or bounds mesh, of any generation, fails, and so does any call removing it."""
    remove = removal._batch_remove  # noqa: SLF001 - the step's module function

    def failing(datablocks: Sequence[bpy.types.ID]) -> None:
        if any(d.name.split(".")[0] == FAILING for d in datablocks):
            raise RuntimeError("injected failure")
        remove(datablocks)

    monkeypatch.setattr(removal, "_batch_remove", failing)


def _counted_removals(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The lengths of the calls removing datablocks, as they're made."""
    remove = removal._batch_remove  # noqa: SLF001 - the step's module function
    calls: list[int] = []

    def counted(datablocks: Sequence[bpy.types.ID]) -> None:
        calls.append(len(datablocks))
        remove(datablocks)

    monkeypatch.setattr(removal, "_batch_remove", counted)
    return calls


def test_a_failed_retirement_completes_with_issues(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # TXN-07, DIAG-02, DIAG-06, DIAG-10, STAB-02 on F-RETIREMENT-FAILURE "retirement": the generation at 10 is
    # published and displayed; the two obsolete resources are in the ledger, retryable, noncanonical, linked in no
    # scene, and reported once each in the result and its cleanup status.
    with transaction.retirement_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        first, second = scene.time_codes
        assert handle.synchronize(first).state is ResultState.SUCCESS
        old = {e.datablock for e in _manifest(handle).entries.values()}
        old_uids = {d.session_uid for d in old if d is not None}
        _fail_retirement(monkeypatch)
        result = handle.synchronize(second)
        assert result.state is scene.outcome
        assert all(d.category is DiagnosticCategory.PENDING_CLEANUP for d in result.diagnostics)
        assert [d.code for d in result.diagnostics] == [DiagnosticCode.RETIREMENT_FAILED] * 2
        assert sorted(d.role for d in result.diagnostics) == sorted(scene.failed_retirements)
        # The new generation is published and displayed.
        generation = binding_state.read_generation(bpy.data.collections["Shot"])
        assert isinstance(generation, Loaded) and generation.record.time_code == second
        published = {e.datablock for e in _manifest(handle).entries.values()}
        assert set(bpy.data.collections["Shot"].objects) == {d for d in published if isinstance(d, bpy.types.Object)}
        assert len(published) == transaction.resource_count(PayloadPolicy.LOAD_ALL)
        # The leftovers: the ledger's, each with the diagnostic naming its ledger key and role.
        ledger = _ledger()
        assert {e.diagnostic for e in ledger.values()} == set(result.diagnostics)
        assert all(e.diagnostic.resource == k for k, e in ledger.items())
        assert result.cleanup_status == tuple(e.diagnostic for _, e in sorted(ledger.items()))
        leftovers = [e.datablock for e in ledger.values()]
        assert sorted(d.name for d in leftovers if d is not None) == [FAILING, FAILING]
        for datablock in leftovers:
            assert datablock is not None and datablock.session_uid in old_uids
            assert ownership.of(datablock).claims == ()  # noncanonical: no manifest names it
            assert datablock not in published
        [obj] = (d for d in leftovers if isinstance(d, bpy.types.Object))
        assert obj.users_collection == ()  # linked in no scene
        # Every other obsolete resource is gone, so only the leftovers add to the counts.
        remaining = {d.session_uid for d in (*bpy.data.objects, *bpy.data.meshes)}
        assert remaining & old_uids == {d.session_uid for d in leftovers if d is not None}
        attempt = binding_state.read_last_attempt(destination(handle))
        assert isinstance(attempt, Loaded) and attempt.record.diagnostics == result.diagnostics


def test_a_repeated_retirement_failure_reports_each_leftover_once(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # DIAG-06 on F-RETIREMENT-FAILURE "repeat": synchronizing again with retirement still failing leaves the earlier
    # leftovers as they were and adds this one's, each in the cleanup status once.
    with transaction.retirement_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        first, second = scene.time_codes
        assert handle.synchronize(first).state is ResultState.SUCCESS
        _fail_retirement(monkeypatch)
        earlier = handle.synchronize(second)
        before = _ledger()
        again = handle.synchronize(second)
        assert again.state is scene.outcome
        assert len(again.diagnostics) == 2
        assert set(again.diagnostics).isdisjoint(earlier.diagnostics)  # this attempt's leftovers, not the earlier
        after = _ledger()
        assert {k: after[k] for k in before} == before
        assert set(again.cleanup_status) == {*earlier.diagnostics, *again.diagnostics}
        assert len(again.cleanup_status) == len(after) == 4


def test_a_replacement_takes_its_resources_identities(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ROLE-02, ROLE-03, ROLE-05 on F-RETIREMENT-FAILURE "identities": each placeholder's resources keep their keys
    # and identities, whatever the objects are named, and retirement removes exactly the replaced datablocks, in a
    # call per level.
    with transaction.retirement_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        first, second = scene.time_codes
        assert handle.synchronize(first).state is ResultState.SUCCESS
        before = _manifest(handle)
        identities = {k: e.identity for k, e in before.entries.items()}
        assert None not in identities.values() and len(set(identities.values())) == len(identities)
        old_uids = {e.datablock.session_uid for e in before.entries.values() if e.datablock is not None}
        for obj in bpy.data.collections["Shot"].objects:
            obj.name = f"Renamed {obj.name}"
        calls = _counted_removals(monkeypatch)
        assert handle.synchronize(second).state is ResultState.SUCCESS
        assert calls == [len(transaction.DRAWN[PayloadPolicy.LOAD_ALL])] * 2  # one call per level: objects, meshes
        after = _manifest(handle)
        assert {k: e.identity for k, e in after.entries.items()} == identities
        assert old_uids.isdisjoint(d.session_uid for d in (*bpy.data.objects, *bpy.data.meshes))
        assert _ledger() == {}


def test_an_obsolete_resource_something_else_uses_is_released_intact(bindings: Bindings, tmp_path: Path) -> None:
    # Refresh leaves a resource that unmanaged content uses intact, released from management: here an object also
    # linked in a collection of the user's, and the bounds mesh it uses (lifecycle.md#ownership-and-lifecycle).
    with transaction.retirement_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        first, second = scene.time_codes
        assert handle.synchronize(first).state is ResultState.SUCCESS
        kept = bpy.data.collections["Shot"].objects[FAILING]
        mesh = kept.data
        users = bpy.data.collections.new("Mine")
        bpy.data.scenes["Scene"].collection.children.link(users)
        users.objects.link(kept)
        assert handle.synchronize(second).state is ResultState.SUCCESS
        assert kept.name in bpy.data.objects and kept.data == mesh and set(kept.users_collection) == {users}
        assert ownership.of(kept).claims == ()
        assert _ledger() == {}  # released, so no retry deletes it


def test_a_retirement_the_ledger_cant_record_raises(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # API-05: a ledger write failing as retirement records its leftovers is a defect, and raises, after the
    # generation is published.
    with transaction.retirement_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        first, second = scene.time_codes
        assert handle.synchronize(first).state is ResultState.SUCCESS
        _fail_retirement(monkeypatch)
        write = pending_cleanup.set_ledger_entries

        def failing(changed: Mapping[str, LedgerEntry], removed: Sequence[str] = ()) -> None:
            if changed:  # retirement's record of its leftovers, the one write here
                raise RuntimeError("injected ledger failure")
            write(changed, removed)

        monkeypatch.setattr(pending_cleanup, "set_ledger_entries", failing)
        with pytest.raises(RuntimeError, match="injected ledger failure"):
            handle.synchronize(second)
        generation = binding_state.read_generation(bpy.data.collections["Shot"])
        assert isinstance(generation, Loaded) and generation.record.time_code == second
