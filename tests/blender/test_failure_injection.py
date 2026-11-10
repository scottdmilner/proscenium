"""Failures injected at the transaction's boundaries before publication (M5 plan, D13; pipeline.md).

On F-FAILED-SETTINGS, F-DIRTY-LAYER, and F-SOURCE-CHANGE. Each failure is injected by patching a module function the
transaction calls, or the core's own error path, so src/ has no hooks, and each test compares the whole published
generation before and after through published.py (TLAY-03). Preparation fails through PreparationResources.track,
which the stub and M7's application layer share, so these tests rerun unchanged against M7's.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import bpy
import pytest

from fixtures import source_access, transaction
from proscenium.binding.results import DiagnosticCategory, DiagnosticCode, ResultState
from proscenium.binding.runtime import pending_cleanup
from proscenium.binding.source_access.stages import PayloadPolicy
from proscenium.core import _core
from proscenium.synchronization import application, prepared_work
from support.usd import binding_on_file

from .published import datablocks, published_generation

if TYPE_CHECKING:
    from pxr import Usd

    from fixtures.transaction import FailedSettingsScene, TransactionScene
    from proscenium.api.bindings import BindingHandle, Bindings
    from proscenium.binding.persistence.manifests import RepresentationRole


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _binding(
    bindings: Bindings, scene: TransactionScene, policy: PayloadPolicy = PayloadPolicy.LOAD_ALL
) -> BindingHandle:
    handle = bindings.create_binding(_scene(), payload_policy=policy, name="Shot")
    assert handle.attach(scene.caller).state is ResultState.SUCCESS
    return handle


def _published(handle: BindingHandle) -> dict[str, Any]:
    return published_generation(handle.binding_id, bpy.data.collections["Shot"])


def _attempting(bindings: Bindings, scene: FailedSettingsScene) -> BindingHandle:
    """F-FAILED-SETTINGS' binding, published, with its attempted settings requested."""
    (policy, time_code), (attempted, _) = scene.published, scene.attempted
    handle = _binding(bindings, scene, policy)
    assert handle.synchronize(time_code).state is ResultState.SUCCESS
    assert handle.set_settings(payload_policy=attempted).state is ResultState.SUCCESS
    return handle


def _no_pending(handle: BindingHandle) -> bool:
    return pending_cleanup.nothing_pending(handle.binding_id)


def _raising(*_args: object) -> None:
    raise RuntimeError("injected failure")


def _failing_after(monkeypatch: pytest.MonkeyPatch, held: int) -> None:
    """Make preparation fail right after its held-th resource is made and held."""
    track = prepared_work.PreparationResources.track
    calls: list[None] = []

    def failing(
        work: prepared_work.PreparationResources, entry_key: str, role: RepresentationRole, d: bpy.types.ID
    ) -> None:
        track(work, entry_key, role, d)
        calls.append(None)
        if len(calls) == held:
            raise RuntimeError("injected preparation failure")

    monkeypatch.setattr(prepared_work.PreparationResources, "track", failing)


ATTEMPTED_RESOURCES = transaction.resource_count(PayloadPolicy.LOAD_NONE)  # F-FAILED-SETTINGS' attempt's


@pytest.mark.parametrize("held", range(1, ATTEMPTED_RESOURCES + 1))
def test_a_failure_at_each_preparation_step_disposes_of_its_work(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held: int
) -> None:
    # TXN-02, TLAY-03 on F-FAILED-SETTINGS "failed-attempt": failing after each prepared resource in turn, the
    # published generation is whole and unchanged, and everything prepared is disposed of, leaving nothing pending.
    with transaction.failed_settings(tmp_path) as scene:
        handle = _attempting(bindings, scene)
        published, before = _published(handle), datablocks()
        _failing_after(monkeypatch, held)
        result = handle.synchronize(scene.attempted[1])
        assert [d.code for d in result.diagnostics] == [DiagnosticCode.PREPARATION_FAILED]
        assert _published(handle) == published
        assert datablocks() == before
        assert _no_pending(handle)


def _core_error_at_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(_stage: Usd.Stage) -> None:
        _core._post_tf_error("injected core error")  # noqa: SLF001 - the core's error path, for tests

    monkeypatch.setattr(_core, "SceneIndexChain", failing)


def _core_error_at_planning(monkeypatch: pytest.MonkeyPatch) -> None:
    # The core refuses a representation version it doesn't plan, through its own error translation.
    monkeypatch.setattr(application, "REPRESENTATION_VERSION", application.REPRESENTATION_VERSION + 1)


@pytest.mark.parametrize(
    ("inject", "code"),
    [
        (_core_error_at_evaluation, DiagnosticCode.EVALUATION_FAILED),
        (_core_error_at_planning, DiagnosticCode.PLANNING_FAILED),
    ],
    ids=["evaluation", "planning"],
)
def test_a_core_error_fails_before_touching_the_display(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inject: Any, code: DiagnosticCode
) -> None:
    # BND-03, API-04 on F-FAILED-SETTINGS "failed-attempt": a Tf error the core raises is the attempt's fatal
    # diagnostic, never an exception, and every datablock in the file stays as it was, nothing prepared.
    with transaction.failed_settings(tmp_path) as scene:
        handle = _attempting(bindings, scene)
        published, before = _published(handle), datablocks()
        prepared: list[None] = []
        new_preparation_resources = prepared_work.new_preparation_resources
        monkeypatch.setattr(
            prepared_work,
            "new_preparation_resources",
            lambda *a: prepared.append(None) or new_preparation_resources(*a),
        )
        inject(monkeypatch)
        result = handle.synchronize(scene.attempted[1])
        assert result.state is ResultState.FATAL_FAILURE
        [diagnostic] = result.diagnostics
        assert diagnostic.code is code
        assert (_published(handle), datablocks(), prepared) == (published, before, [])


def test_nothing_changes_before_preparation(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BND-02 on F-FAILED-SETTINGS: when preparation starts, the attempt has created and changed no datablock.
    with transaction.failed_settings(tmp_path) as scene:
        handle = _attempting(bindings, scene)
        published, before = _published(handle), datablocks()
        at_preparation: list[tuple[object, ...]] = []
        new_preparation_resources = prepared_work.new_preparation_resources

        def noting(*args: Any) -> prepared_work.PreparationResources:
            at_preparation.append((_published(handle), datablocks()))
            return new_preparation_resources(*args)

        monkeypatch.setattr(prepared_work, "new_preparation_resources", noting)
        _failing_after(monkeypatch, 1)
        assert handle.synchronize(scene.attempted[1]).state is ResultState.FATAL_FAILURE
        assert at_preparation == [(published, before)]


def test_source_state_is_reported_when_preparation_fails(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BND-02 on F-DIRTY-LAYER "as-loaded": with preparation failing at its first step, the attempt reports the
    # source-state diagnostic its successful synchronization reports, since it exists before preparation. The scene
    # plans no placeholders, so preparation fails as it starts.
    with source_access.dirty_layer(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root)
        succeeded = handle.synchronize(0)
        assert succeeded.state is ResultState.SUCCESS
        monkeypatch.setattr(application, "prepare", _raising)
        failed = handle.synchronize(0)
        assert failed.state is ResultState.FATAL_FAILURE

        def source_state(diagnostics: tuple[Any, ...]) -> list[Any]:
            return [d for d in diagnostics if d.category is DiagnosticCategory.SOURCE_STATE]

        assert source_state(succeeded.diagnostics)
        assert source_state(failed.diagnostics) == source_state(succeeded.diagnostics)


def test_a_source_change_during_evaluation_discards_the_attempt(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CONS-03 on F-SOURCE-CHANGE "during-evaluation": the attempt fails before publication with a diagnostic naming
    # sub.usda, the published generation is unchanged, and the next synchronization shows the change.
    with transaction.source_change(tmp_path) as scene:
        handle = _binding(bindings, scene)
        assert handle.synchronize(0).state is ResultState.SUCCESS
        published, before = _published(handle), datablocks()
        chain = _core.SceneIndexChain

        def editing(stage: Usd.Stage) -> _core.SceneIndexChain:
            scene.edit()  # as a caller editing the source during the synchronization would
            return chain(stage)

        with monkeypatch.context() as patch:  # not monkeypatch.undo(), which would undo the bindings fixture's too
            patch.setattr(_core, "SceneIndexChain", editing)
            result = handle.synchronize(0)
        assert result.state is ResultState.FATAL_FAILURE
        [diagnostic] = result.diagnostics
        assert diagnostic.code is DiagnosticCode.SOURCE_CHANGED
        assert [Path(layer) for layer in diagnostic.layers] == [scene.sub_layer]
        assert (_published(handle), datablocks()) == (published, before)
        assert handle.synchronize(0).state is ResultState.SUCCESS
        assert _published(handle)["content"] != published["content"]
