"""Publication, and the records a synchronization writes: the generation and the last attempt (M5 plan, D6).

On F-PUBLICATION-FAILURE and F-FAILED-SETTINGS (fixtures/transaction.py). A failure is injected by patching the step's
module function, so src/ has no hooks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest
from pxr import Usd

from fixtures import transaction
from fixtures.transaction import Step
from proscenium.binding.persistence import binding_state, manifests, records
from proscenium.binding.persistence.binding_state import Generation, LastAttempt
from proscenium.binding.persistence.records import Loaded
from proscenium.binding.results import DiagnosticCode, Result, ResultState
from proscenium.binding.runtime import ownership_index, pending_cleanup
from proscenium.binding.source_access.stages import PayloadPolicy
from proscenium.core import _core
from proscenium.synchronization import application, publication
from support.blend import save_and_reopen

from .published import datablocks, published_generation

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from fixtures.transaction import TransactionScene
    from proscenium.api.bindings import BindingHandle, Bindings

# What a failure at each step before publication reports.
FAILED = {
    Step.ACQUIRE: DiagnosticCode.NO_ATTACHED_STAGE,
    Step.EVALUATE: DiagnosticCode.EVALUATION_FAILED,
    Step.PLAN: DiagnosticCode.PLANNING_FAILED,
    Step.PREPARE: DiagnosticCode.PREPARATION_FAILED,
    Step.PUBLISH: DiagnosticCode.PUBLICATION_FAILED,
}
PUBLICATION_WRITES = ("manifest", "generation", "ledger")  # the destination's links are written first


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _binding(bindings: Bindings, scene: TransactionScene, policy: PayloadPolicy) -> BindingHandle:
    handle = bindings.create_binding(_scene(), payload_policy=policy, name="Shot")
    assert handle.attach(scene.caller).state is ResultState.SUCCESS
    return handle


def _destination() -> bpy.types.Collection:
    return bpy.data.collections["Shot"]


def _published(handle: BindingHandle) -> dict[str, Any]:
    return published_generation(handle.binding_id, _destination())


def _ledger_entries() -> dict[str, object]:
    ledger = pending_cleanup.ledger()
    assert not isinstance(ledger, records.RefusedRecord)
    return {} if ledger is None else dict(ledger.record.entries)


def _last_attempt(handle: BindingHandle) -> object:
    return binding_state.read_last_attempt(_scene(), handle.binding_id)


def _raising(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("injected failure")


def _once(original: Callable[..., Any], when: Callable[..., bool]) -> Callable[..., Any]:
    """original, raising the first time it's called with arguments when accepts."""
    failed = []

    def call(*args: object, **kwargs: object) -> Any:
        if not failed and when(*args, **kwargs):
            failed.append(True)
            raise RuntimeError("injected failure")
        return original(*args, **kwargs)

    return call


def _fail_publication_write(monkeypatch: pytest.MonkeyPatch, write: str) -> None:
    """Make one of publication's writes fail; disposal's own ledger write afterwards succeeds."""
    if write == "manifest":
        monkeypatch.setattr(ownership_index, "set_manifest", _raising)
    elif write == "generation":
        monkeypatch.setattr(binding_state, "write_generation", _raising)
    else:  # the ledger update that resolves the prepared work: the first that removes entries
        resolving = _once(pending_cleanup.set_ledger_entries, lambda _changed, removed=(): bool(removed))
        monkeypatch.setattr(pending_cleanup, "set_ledger_entries", resolving)


def _fail_step(monkeypatch: pytest.MonkeyPatch, handle: BindingHandle, step: Step) -> None:
    if step is Step.ACQUIRE:
        handle.release()  # a source reason: the caller's stage is no longer attached
        return
    module, name = {
        Step.EVALUATE: (_core, "SceneIndexChain"),
        Step.PLAN: (_core, "plan"),
        Step.PREPARE: (application, "prepare"),
        Step.PUBLISH: (publication, "publish"),
    }[step]
    monkeypatch.setattr(module, name, _raising)


def test_a_publication_switches_the_whole_generation(bindings: Bindings, tmp_path: Path) -> None:
    # TXN-06: a publication that succeeds makes the manifest, the generation record, and the destination's links all
    # new, and leaves nothing pending or staged; retirement removes what the earlier one published.
    with transaction.publication_failure(tmp_path) as scene:
        handle = _binding(bindings, scene, PayloadPolicy.LOAD_ALL)
        assert handle.synchronize(10) == Result(time_codes=(Usd.TimeCode(10),))
        first = _published(handle)
        manifest = manifests.read_manifest(_destination())
        assert isinstance(manifest, Loaded)
        named = {e.datablock for e in manifest.record.entries.values()}
        assert len(named) == transaction.resource_count(PayloadPolicy.LOAD_ALL)
        assert first["objects"] == {d.session_uid for d in named if isinstance(d, bpy.types.Object)}
        stages = bindings.stages.get(handle.binding_id)
        assert stages is not None
        expected = Generation(handle.binding_id, PayloadPolicy.LOAD_ALL, 10.0, stages.source_revision, ())
        assert binding_state.read_generation(_destination()) == Loaded(expected, 1)
        assert _ledger_entries() == {}
        assert [c.name for c in bpy.data.collections] == ["Shot"]  # the staging collection is gone
        uids = {d.session_uid for d in named if d is not None}  # a removed datablock can't be compared
        assert handle.synchronize(12).state is ResultState.SUCCESS
        second = _published(handle)
        assert uids.isdisjoint(second["objects"])
        assert second["manifest"] != first["manifest"]
        assert second["generation"] != first["generation"]
        assert uids.isdisjoint(d.session_uid for d in (*bpy.data.objects, *bpy.data.meshes))  # retired
        assert _ledger_entries() == {}


@pytest.mark.parametrize("write", PUBLICATION_WRITES)
def test_a_failed_first_publication_leaves_nothing(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write: str
) -> None:
    # TXN-04, TXN-06 on F-PUBLICATION-FAILURE "first": a failure at each of publication's writes in turn leaves no
    # manifest, generation, or content, and its prepared work disposed of.
    with transaction.publication_failure(tmp_path) as scene:
        handle = _binding(bindings, scene, PayloadPolicy.LOAD_ALL)
        nothing, before = _published(handle), datablocks()
        _fail_publication_write(monkeypatch, write)
        result = handle.synchronize(10)
        assert result.state is scene.outcome
        assert [d.code for d in result.diagnostics] == [DiagnosticCode.PUBLICATION_FAILED]
        assert _published(handle) == nothing
        assert ownership_index.manifest(handle.binding_id) is None
        assert datablocks() == before
        assert _ledger_entries() == {}


@pytest.mark.parametrize("write", PUBLICATION_WRITES)
def test_a_failed_publication_keeps_the_published_generation(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write: str
) -> None:
    # TXN-02, TXN-06 on F-PUBLICATION-FAILURE "replace": the earlier generation stays whole, its records and links as
    # they were, and the claims on its resources with them.
    with transaction.publication_failure(tmp_path) as scene:
        handle = _binding(bindings, scene, PayloadPolicy.LOAD_ALL)
        assert handle.synchronize(10).state is ResultState.SUCCESS
        published, before = _published(handle), datablocks()
        _fail_publication_write(monkeypatch, write)
        result = handle.synchronize(12)
        assert [d.code for d in result.diagnostics] == [DiagnosticCode.PUBLICATION_FAILED]
        assert _published(handle) == published
        assert all(ownership_index.ownership(obj).claims for obj in _destination().objects)
        assert datablocks() == before
        assert _ledger_entries() == {}


@pytest.mark.parametrize("step", transaction.BEFORE_PUBLICATION)
def test_a_failed_attempt_keeps_the_generation_and_records_itself(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: Step
) -> None:
    # STATE-02, STATE-03, DIAG-04 on F-FAILED-SETTINGS "failed-attempt": published under load-all at 10, then
    # load-none requested and attempted at 20, which fails at step. The generation keeps its settings, time code, and
    # diagnostics; the last attempt holds the failure's; each through save and reopen.
    with transaction.failed_settings(tmp_path) as scene:
        (published_policy, published_time), (attempted_policy, attempted_time) = scene.published, scene.attempted
        handle = _binding(bindings, scene, published_policy)
        assert handle.synchronize(published_time).state is ResultState.SUCCESS
        assert _last_attempt(handle) == Loaded(LastAttempt(published_policy, published_time, ()), 1)
        published = _published(handle)
        generation = binding_state.read_generation(_destination())
        assert isinstance(generation, Loaded)
        assert handle.set_settings(payload_policy=attempted_policy).state is ResultState.SUCCESS
        _fail_step(monkeypatch, handle, step)
        before = datablocks()
        result = handle.synchronize(attempted_time)
        assert result.state is scene.outcome
        assert [d.code for d in result.diagnostics] == [FAILED[step]]
        assert _published(handle) == published
        assert datablocks() == before  # prepared work disposed of
        attempt = LastAttempt(attempted_policy, attempted_time, result.diagnostics)
        assert _last_attempt(handle) == Loaded(attempt, 1)
        monkeypatch.undo()
        save_and_reopen(tmp_path / "failed.blend")
        assert binding_state.read_generation(_destination()) == generation
        assert generation.record.payload_policy is published_policy
        assert generation.record.time_code == published_time
        assert _last_attempt(handle) == Loaded(attempt, 1)


def test_every_outcome_records_the_last_attempt(bindings: Bindings, tmp_path: Path) -> None:
    # STATE-03: a refusal before the source is read is an attempt too; one the binding can't make isn't.
    with transaction.failed_settings(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        result = handle.synchronize(4)
        assert [d.code for d in result.diagnostics] == [DiagnosticCode.NO_ATTACHED_STAGE]
        assert _last_attempt(handle) == Loaded(LastAttempt(PayloadPolicy.LOAD_ALL, 4.0, result.diagnostics), 1)
        assert handle.attach(scene.caller).state is ResultState.SUCCESS
        assert handle.synchronize(Usd.TimeCode.Default()).state is ResultState.SUCCESS
        assert _last_attempt(handle) == Loaded(LastAttempt(PayloadPolicy.LOAD_ALL, None, ()), 1)
