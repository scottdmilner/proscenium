"""Undo steps of synchronizations and cleanup retries, and what undo restores (lifecycle.md#undo-and-runtime-state).

On F-FAILED-SETTINGS and F-PREPARATION-CLEANUP-FAILURE (fixtures/transaction.py), M5 plan, D12. Steps are pushed only
outside background mode, which the bpy wheel always is, so tests that count them patch the API's _undo_steps_enabled;
with global undo on, the wheel undoes them as Blender would (runtime-record.md#undo). Each test pushes a base step after
making a marker object, so an undo that reaches past the operation's one step removes the marker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy
import pytest

from fixtures import transaction
from proscenium.api import bindings as api
from proscenium.binding.persistence import binding_state, id_property_records, manifests
from proscenium.binding.results import Result, ResultState
from proscenium.binding.runtime import ownership, pending_cleanup
from proscenium.core import _core
from proscenium.synchronization import datablock_removal
from support import undo

from .transaction_failures import failing_preparation

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

    from fixtures.transaction import TransactionScene
    from proscenium.api.bindings import BindingHandle, Bindings

MARKER = "Undo base"


@pytest.fixture
def pushing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Push undo steps as Blender with global undo on, outside background mode, would."""
    undo.require_global_undo()
    monkeypatch.setattr(api, "_undo_steps_enabled", lambda: True)


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _binding(bindings: Bindings, scene: TransactionScene) -> BindingHandle:
    handle = bindings.create_binding(_scene(), name="Shot")
    assert handle.attach(scene.caller).state is ResultState.SUCCESS
    return handle


def _base() -> None:
    """Mark the state, and push the step an undo past the operation's one would return to."""
    bpy.data.objects.new(MARKER, None)
    undo.push("base")


def _shown() -> dict[str, Any]:
    """What undo restores, by value, since references to datablocks an undo touched don't survive it."""
    destination = bpy.data.collections["Shot"]
    return {
        "base": MARKER in bpy.data.objects,
        "generation": id_property_records.stored(destination, binding_state.GENERATION_KEY),
        "objects": sorted(o.name for o in destination.objects),
    }


def _key(datablock: bpy.types.ID) -> tuple[str, str]:
    """A datablock by kind and name, since an object and its bounds mesh share a name."""
    return type(datablock).__name__, datablock.name


def _ledger_names() -> set[tuple[str, str]]:
    ledger = pending_cleanup.ledger()
    assert not isinstance(ledger, id_property_records.RefusedRecord)
    entries = {} if ledger is None else ledger.record.entries
    assert all(e.datablock is not None for e in entries.values())  # each names a datablock in the file
    return {_key(e.datablock) for e in entries.values() if e.datablock is not None}


def _managed_names(handle: BindingHandle) -> set[tuple[str, str]]:
    manifest = ownership.manifest(handle.binding_id)
    if manifest is None:
        return set()
    assert isinstance(manifest, id_property_records.LoadedRecord)
    return {_key(e.datablock) for e in manifest.record.entries.values() if e.datablock is not None}


def _names() -> set[tuple[str, str]]:
    return {_key(d) for d in (*bpy.data.objects, *bpy.data.meshes)}


@pytest.mark.usefixtures("pushing")
def test_a_publication_is_one_undo_step(bindings: Bindings, tmp_path: Path) -> None:
    # UNDO-02, UNDO-05 on F-FAILED-SETTINGS "undo-steps": undo restores the previous generation, which leaves the
    # binding possibly out of date until it synchronizes again; redo restores the later one, the last it published.
    with transaction.failed_settings(tmp_path) as scene:
        handle = _binding(bindings, scene)
        assert handle.synchronize(scene.published[1]).state is ResultState.SUCCESS
        _base()
        earlier = _shown()
        policy, time_code = scene.attempted
        handle.set_settings(payload_policy=policy)
        assert handle.synchronize(time_code).state is ResultState.SUCCESS
        later = _shown()
        assert later["generation"] != earlier["generation"]
        assert not handle.possibly_out_of_date()
        undo.undo()
        assert _shown() == earlier
        assert handle.possibly_out_of_date()
        undo.redo()
        assert _shown() == later
        assert not handle.possibly_out_of_date()
        undo.undo()
        assert handle.synchronize(time_code).state is ResultState.SUCCESS
        assert not handle.possibly_out_of_date()


class _SynchronizeOperator(bpy.types.Operator):
    """An operator calling the API, as an extension's would: it declares no UNDO, so the API's step is its only one."""

    bl_idname = "proscenium_test.synchronize"
    bl_label = "Synchronize"
    bl_options = {"REGISTER"}  # noqa: RUF012 - Blender reads it as a class attribute

    binding_id: bpy.props.StringProperty()  # ty: ignore[invalid-type-form]
    time_code: bpy.props.FloatProperty()  # ty: ignore[invalid-type-form]

    @override
    def execute(self, context: bpy.types.Context | None) -> set[OperatorReturnItems]:  # noqa: ARG002
        api.BindingHandle(self.binding_id).synchronize(self.time_code)
        return {"FINISHED"}


@pytest.fixture
def operator() -> Generator[None]:
    bpy.utils.register_class(_SynchronizeOperator)
    yield
    bpy.utils.unregister_class(_SynchronizeOperator)


@pytest.mark.usefixtures("pushing", "operator")
def test_an_operator_calling_the_api_adds_one_step(bindings: Bindings, tmp_path: Path) -> None:
    # UNDO-02: called with undo, as the interface calls an operator, it still adds exactly one step.
    with transaction.failed_settings(tmp_path) as scene:
        handle = _binding(bindings, scene)
        _base()
        before = _shown()
        call = bpy.ops.proscenium_test.synchronize  # ty: ignore[unresolved-attribute]
        assert call("EXEC_DEFAULT", True, binding_id=handle.binding_id, time_code=10) == {"FINISHED"}
        published = _shown()
        assert published["objects"]
        undo.undo()
        assert _shown() == before
        undo.redo()
        assert _shown() == published


@pytest.mark.usefixtures("pushing")
def test_a_failed_synchronization_adds_no_step(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # UNDO-03 on F-FAILED-SETTINGS "failed-attempt": undo after the failure restores the state before the last
    # publication, which a step of the failure's own would have kept.
    with transaction.failed_settings(tmp_path) as scene:
        handle = _binding(bindings, scene)
        _base()
        before = _shown()
        assert handle.synchronize(scene.published[1]).state is ResultState.SUCCESS
        with monkeypatch.context() as patch:
            patch.setattr(_core, "plan", lambda *_: (_ for _ in ()).throw(RuntimeError("injected failure")))
            assert handle.synchronize(scene.attempted[1]).state is scene.outcome
        undo.undo_unpushed()
        assert _shown() == before


def test_background_mode_pushes_no_step(bindings: Bindings, tmp_path: Path) -> None:
    # UNDO-04 on F-FAILED-SETTINGS "undo-steps": in background mode the same synchronization publishes the same
    # generation, and the undo after it reaches past the base step, since it pushed none. With global undo off nothing
    # can be undone here (runtime-record.md#undo), so that case isn't checked.
    undo.require_global_undo()
    assert bpy.app.background
    with transaction.failed_settings(tmp_path) as scene:
        handle = _binding(bindings, scene)
        undo.push("before base")  # a step for the undo to reach
        _base()
        policy, time_code = scene.published
        assert handle.synchronize(time_code).state is ResultState.SUCCESS
        generation = binding_state.read_generation(bpy.data.collections["Shot"])
        assert isinstance(generation, id_property_records.LoadedRecord)
        assert (generation.record.applied_settings.payload_policy, generation.record.time_code) == (policy, time_code)
        undo.undo_unpushed()
        assert MARKER not in bpy.data.objects


@pytest.mark.usefixtures("pushing")
def test_a_committed_retry_is_one_step_and_a_failed_one_none(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A retry that resolves nothing, or has nothing to retry, pushes no step; one that commits pushes one, whose undo
    # brings the leftovers and their entries back (lifecycle.md: cleanup supports undo, one step per invocation that
    # commits).
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        _, leftovers = failing_preparation(handle, scene, 0)
        names = {_key(d) for d in leftovers}
        _base()
        with monkeypatch.context() as patch:
            patch.setattr(
                datablock_removal, "_batch_remove", lambda _: (_ for _ in ()).throw(RuntimeError("injected failure"))
            )
            assert handle.retry_cleanup().state is ResultState.FATAL_FAILURE
        assert handle.retry_cleanup().state is ResultState.SUCCESS
        assert names.isdisjoint(_names()) and _ledger_names() == set()
        assert handle.retry_cleanup() == Result()  # nothing pending: no step either
        undo.undo()
        assert MARKER in bpy.data.objects  # neither the failed retry nor the empty one pushed a step
        assert _ledger_names() == names <= _names()
        undo.redo()
        assert names.isdisjoint(_names()) and _ledger_names() == set()


@pytest.mark.usefixtures("pushing")
def test_undo_restores_the_ledger_with_the_ownership_it_tracks(bindings: Bindings, tmp_path: Path) -> None:
    # PEND-05 on F-PREPARATION-CLEANUP-FAILURE "undo": after the failed attempt and a publication, undo and redo each
    # leave every ledger entry naming a datablock in the file, and every leftover named by an entry.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        _base()
        baseline = _names()
        failing_preparation(handle, scene, 0)
        assert handle.synchronize(0).state is ResultState.SUCCESS

        def check() -> None:
            leftovers = _names() - baseline - _managed_names(handle)
            assert _ledger_names() == leftovers

        check()
        undo.undo()
        assert MARKER in bpy.data.objects and _ledger_names() == set()
        check()
        undo.redo()
        assert _ledger_names()
        check()


@pytest.mark.usefixtures("pushing")
def test_undoing_a_deletion_of_managed_content_restores_its_ownership(bindings: Bindings, tmp_path: Path) -> None:
    # Undo after deleting stub content leaves the ownership index consistent with the manifest again.
    with transaction.failed_settings(tmp_path) as scene:
        handle = _binding(bindings, scene)
        assert handle.synchronize(scene.published[1]).state is ResultState.SUCCESS
        _base()
        managed = _managed_names(handle)
        deleted = bpy.data.collections["Shot"].objects[0].name
        bpy.data.objects.remove(bpy.data.objects[deleted])
        undo.push("delete")
        assert ("Object", deleted) not in _managed_names(handle)
        undo.undo()
        assert _managed_names(handle) == managed
        manifest = ownership.manifest(handle.binding_id)
        assert manifest == manifests.read_manifest(bpy.data.collections["Shot"])  # held as stored
        claims = ownership.of(bpy.data.objects[deleted]).claims
        assert [c.binding_id for c in claims] == [handle.binding_id]
