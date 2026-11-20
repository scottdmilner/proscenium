"""Removing a binding with its managed content (lifecycle.md#ownership-and-lifecycle).

The Stage Output bindings plan's step 1, ahead of M11.

On F-UNMANAGED-USER (fixtures/incremental.py), whose content a test may give unmanaged users before removing, on
F-BINDING-STATE for the handles of a removed binding, and on F-PREPARATION-CLEANUP-FAILURE for a binding with leftovers.
Failures are injected by patching the removal module's function, so src/ has no hooks. Undo steps are pushed only
outside background mode, which the bpy wheel always is, so the undo test patches the API's _undo_steps_enabled.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import incremental, source_access, transaction
from fixtures import schema_version_cases as record_fixtures
from proscenium_sync.bindings import BindingNotFoundError
from proscenium_sync.bindings import binding_service as api
from proscenium_sync.persistence import binding_records, cleanup_ledgers, id_property_records
from proscenium_sync.persistence.manifests import RepresentationRole
from proscenium_sync.results import DiagnosticCode, ResultState
from proscenium_sync.runtime import ownership, pending_cleanup
from proscenium_sync.synchronization import datablock_removal
from support import undo
from support.usd import binding_on_file

from .test_resource_stability import UnmanagedState, _unmanaged_users
from .transaction_failures import failing_preparation

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from proscenium_sync.bindings import BindingHandle, Bindings
    from proscenium_sync.persistence.cleanup_ledgers import LedgerEntry


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _synchronized(bindings: Bindings, root: Path, name: str = "Shot") -> BindingHandle:
    handle = binding_on_file(bindings, _scene(), root, name=name)
    assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
    return handle


def _managed(handle: BindingHandle) -> dict[str, bpy.types.ID]:
    """The binding's managed datablocks, by entry key."""
    manifest = ownership.manifest(handle.binding_id)
    assert isinstance(manifest, id_property_records.LoadedRecord)
    return {k: e.datablock for k, e in manifest.record.entries.items() if e.datablock is not None}


def _managed_of(handle: BindingHandle, source: str, role: RepresentationRole) -> bpy.types.ID:
    manifest = ownership.manifest(handle.binding_id)
    assert isinstance(manifest, id_property_records.LoadedRecord)
    [found] = (
        e.datablock
        for e in manifest.record.entries.values()
        if e.role is role and e.source_entity_paths[0] == source and e.datablock is not None
    )
    return found


def _ledger() -> dict[str, LedgerEntry]:
    ledger = pending_cleanup.ledger()
    assert not isinstance(ledger, id_property_records.RefusedRecord)
    return {} if ledger is None else dict(ledger.record.entries)


def _key(datablock: bpy.types.ID) -> tuple[str, str]:
    """A datablock by kind and name, since an object and its bounds mesh share a name."""
    return type(datablock).__name__, datablock.name


def _names() -> set[tuple[str, str]]:
    return {_key(d) for d in (*bpy.data.objects, *bpy.data.meshes, *bpy.data.collections)}


def _fail_removing(monkeypatch: pytest.MonkeyPatch, fail: Callable[[bpy.types.ID], bool]) -> None:
    """Make removing a datablock fail accepts fail, or a call with one."""
    remove = datablock_removal._batch_remove  # noqa: SLF001 - the step's module function

    def failing(datablocks: Sequence[bpy.types.ID]) -> None:
        if any(fail(d) for d in datablocks):
            raise RuntimeError("injected failure")
        remove(datablocks)

    monkeypatch.setattr(datablock_removal, "_batch_remove", failing)


def test_removal_removes_the_content_and_the_destination(bindings: Bindings, tmp_path: Path) -> None:
    # OWN-14: removal removes the binding's configuration and managed content; its destination, left empty, goes with
    # its records, and no scene lists the binding.
    with incremental.unmanaged_user(tmp_path) as scene:
        before = _names()
        handle = _synchronized(bindings, scene.root_layer_path)
        managed = _managed(handle)
        result = handle.remove()
        assert (result.state, result.diagnostics, result.pending_cleanup_diagnostics) == (ResultState.SUCCESS, (), ())
        assert not any(id_property_records.alive(d) for d in managed.values())
        assert _names() == before
        assert bindings.in_scene(_scene()) == []
        assert _ledger() == {}


def test_a_removed_bindings_handles_raise_except_release(bindings: Bindings, tmp_path: Path) -> None:
    # API-08 on F-BINDING-STATE "removed-binding": after removal, each method needing the binding's records raises for
    # its handle, and release, which addresses runtime state, doesn't. Removal released the binding's attachment.
    with source_access.binding_state(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        assert handle.attach(scene.caller).state is ResultState.SUCCESS
        assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        assert handle.remove().state is ResultState.SUCCESS
        assert (stages := bindings.stages.get(handle.binding_id)) is None or stages.live_stage is None
        calls: list[Callable[[], object]] = [
            lambda: handle.attach(scene.caller),
            lambda: handle.synchronize(0),
            lambda: handle.cache([5]),
            lambda: handle.set_settings(coordinate_conversion=False),
            handle.reload,
            handle.retry_cleanup,
            handle.remove,
            handle.possibly_out_of_date,
            handle.requested_settings,
            handle.live_stage,
        ]
        for call in calls:
            with pytest.raises(BindingNotFoundError):
                call()
        handle.release()


def test_removal_leaves_unmanaged_users_as_they_were(bindings: Bindings, tmp_path: Path) -> None:
    # OWN-07, OWN-14, OWN-15 on F-UNMANAGED-USER "binding-removed": Used's bounds mesh, which an unmanaged object uses,
    # is released intact; the unmanaged objects keep their data, transforms, parenting, links, selection, and names,
    # the one linked into the destination included, so the destination stays, an ordinary collection without records.
    with incremental.unmanaged_user(tmp_path) as scene:
        handle = _synchronized(bindings, scene.root_layer_path)
        users = _unmanaged_users(handle)
        before = {key: UnmanagedState.of(obj) for key, obj in users.items()}
        mesh = users["mine"].data
        assert isinstance(mesh, bpy.types.Mesh)
        name, vertices = mesh.name, [v.co[:] for v in mesh.vertices]
        removed = [d for d in _managed(handle).values() if d != mesh]
        result = handle.remove()
        assert (result.state, result.diagnostics) == (ResultState.SUCCESS, ())
        assert {key: UnmanagedState.of(obj) for key, obj in users.items()} == before
        assert (mesh.name, [v.co[:] for v in mesh.vertices]) == (name, vertices)
        assert not any(id_property_records.alive(d) for d in removed)
        destination = bpy.data.collections["Shot"]
        assert list(destination.objects) == [users["visitor"]]
        assert id_property_records.keys(destination) == []
        assert bindings.in_scene(_scene()) == []


def test_removal_keeps_another_bindings_content(bindings: Bindings, tmp_path: Path) -> None:
    # OWN-15, BIND-10: removing one binding leaves another's content, manifest, and synchronization as they were.
    with incremental.unmanaged_user(tmp_path) as scene:
        handle = _synchronized(bindings, scene.root_layer_path)
        other = _synchronized(bindings, scene.root_layer_path, "Other")
        kept = _managed(other)
        assert handle.remove().state is ResultState.SUCCESS
        assert _managed(other) == kept
        assert all(id_property_records.alive(d) for d in kept.values())
        assert bindings.in_scene(_scene()) == [other]
        assert other.synchronize(0).state is not ResultState.FATAL_FAILURE
        assert _managed(other) == kept  # unchanged, so nothing replaced


def test_a_failed_disposal_stays_pending_after_the_binding_is_gone(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # lifecycle.md#lifecycle-failure-safety, LFS-04: Used's object can't be removed, so neither can its bounds mesh.
    # Both stay in the ledger, which outlives the configuration, with removal-failed diagnostics among the result's,
    # so it completes with issues; the object is linked in no collection, and the binding is removed.
    with incremental.unmanaged_user(tmp_path) as scene:
        handle = _synchronized(bindings, scene.root_layer_path)
        used = _managed_of(handle, incremental.USED, RepresentationRole.OBJECT)
        mesh = _managed_of(handle, incremental.USED, RepresentationRole.BOUNDS_MESH)
        assert isinstance(used, bpy.types.Object)
        _fail_removing(monkeypatch, lambda d: d == used)
        result = handle.remove()
        assert result.state is ResultState.COMPLETED_WITH_ISSUES
        assert {d.code for d in result.diagnostics} == {DiagnosticCode.REMOVAL_FAILED}
        assert set(result.pending_cleanup_diagnostics) == set(result.diagnostics)
        ledger = _ledger()
        assert {e.datablock for e in ledger.values()} == {used, mesh}
        assert {(e.binding_id, e.operation) for e in ledger.values()} == {
            (handle.binding_id, cleanup_ledgers.OriginatingOperation.REMOVE)
        }
        assert {e.diagnostic for e in ledger.values()} == set(result.diagnostics)
        assert {d.pending_resource_key for d in result.diagnostics} == ledger.keys()
        assert list(used.users_collection) == []
        assert "Shot" not in bpy.data.collections
        assert bindings.in_scene(_scene()) == []


def test_removal_disposes_of_the_bindings_leftovers(bindings: Bindings, tmp_path: Path) -> None:
    # The binding's leftovers in the ledger are its managed content too, so removal disposes of them and resolves their
    # entries; another binding's stay.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        other = bindings.create_binding(_scene(), name="Other")
        for h in (handle, other):
            assert h.attach(scene.caller).state is ResultState.SUCCESS
        _, leftovers = failing_preparation(handle, scene, 0)
        failing_preparation(other, scene, 0)
        others = {k: e for k, e in _ledger().items() if e.binding_id == other.binding_id}
        result = handle.remove()
        assert (result.state, result.pending_cleanup_diagnostics) == (ResultState.SUCCESS, ())
        assert not any(id_property_records.alive(d) for d in leftovers)
        assert _ledger() == others


def test_a_ledger_that_cant_be_read_refuses_removal(bindings: Bindings, tmp_path: Path) -> None:
    # SCHEMA-03, SCHEMA-06: a ledger that can't be read authorizes no disposal, so removal refuses, changing nothing.
    with (
        incremental.unmanaged_user(tmp_path) as scene,
        record_fixtures.schema_versions(tmp_path / "versions") as versions,
    ):
        handle = _synchronized(bindings, scene.root_layer_path)
        [text] = binding_records.index_texts()
        text[id_property_records.NAMESPACE][cleanup_ledgers.LEDGER_KEY] = versions.ledgers["newer"]
        names = _names()
        result = handle.remove()
        assert result.state is ResultState.FATAL_FAILURE
        [diagnostic] = result.diagnostics
        assert diagnostic.code is DiagnosticCode.UNSUPPORTED_RECORD and "ledger" in diagnostic.message
        assert _names() == names
        assert bindings.in_scene(_scene()) == [handle]


def test_a_removal_is_one_undo_step(bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # UNDO-08: a removal that commits is one undo step; undo restores the binding with its records and content, and
    # redo removes them again.
    undo.require_global_undo()
    monkeypatch.setattr(api, "_undo_steps_enabled", lambda: True)
    with incremental.unmanaged_user(tmp_path) as scene:
        handle = _synchronized(bindings, scene.root_layer_path)
        managed = {_key(d) for d in _managed(handle).values()}
        bpy.data.objects.new("Undo base", None)
        undo.push("base")
        names = _names()
        assert handle.remove().state is ResultState.SUCCESS
        assert bindings.in_scene(_scene()) == []
        undo.undo()
        assert _names() == names  # the base's marker included, so it was one step
        assert bindings.in_scene(_scene()) == [handle]
        assert {_key(d) for d in _managed(handle).values()} == managed
        undo.redo()
        assert bindings.in_scene(_scene()) == []
        assert not managed & _names()


def test_a_leftover_that_fails_again_gets_a_fresh_diagnostic(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As a retry reports it: a leftover whose removal fails again keeps its ledger key and code, with a fresh diagnostic
    # in the ledger and the result, which completes with issues.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        assert handle.attach(scene.caller).state is ResultState.SUCCESS
        failed, leftovers = failing_preparation(handle, scene, 0)
        [mesh] = (d for d in leftovers if isinstance(d, bpy.types.Mesh))
        [(ledger_key, before)] = ((k, e) for k, e in _ledger().items() if e.datablock == mesh)
        _fail_removing(monkeypatch, lambda d: d == mesh)
        result = handle.remove()
        assert result.state is ResultState.COMPLETED_WITH_ISSUES
        [diagnostic] = result.diagnostics
        assert (diagnostic.code, diagnostic.pending_resource_key) == (before.diagnostic.code, ledger_key)
        assert diagnostic != before.diagnostic and diagnostic not in failed.diagnostics
        assert {k: e.diagnostic for k, e in _ledger().items()} == {ledger_key: diagnostic}
        assert bindings.in_scene(_scene()) == []


def _instance_the_destination() -> None:
    """An unmanaged empty instancing the destination, linked into the scene."""
    empty = bpy.data.objects.new("Instancer", None)
    empty.instance_type = "COLLECTION"
    empty.instance_collection = bpy.data.collections["Shot"]
    _scene().collection.objects.link(empty)


def _protect_the_destination() -> None:
    bpy.data.collections["Shot"].use_fake_user = True


@pytest.mark.parametrize("use", [_instance_the_destination, _protect_the_destination], ids=["instanced", "fake-user"])
def test_a_destination_something_uses_stays_without_records(
    bindings: Bindings, tmp_path: Path, use: Callable[[], None]
) -> None:
    # OWN-07: a destination an unmanaged empty instances, or a fake user protects, stays, empty and without records;
    # the binding's content and configuration are removed.
    with incremental.unmanaged_user(tmp_path) as scene:
        handle = _synchronized(bindings, scene.root_layer_path)
        managed = _managed(handle)
        use()
        assert handle.remove().state is ResultState.SUCCESS
        destination = bpy.data.collections["Shot"]
        assert (list(destination.objects), id_property_records.keys(destination)) == ([], [])
        assert not any(id_property_records.alive(d) for d in managed.values())
        if "Instancer" in bpy.data.objects:
            assert bpy.data.objects["Instancer"].instance_collection == destination
        assert bindings.in_scene(_scene()) == []


def test_a_destination_that_cant_be_removed_stays_without_records(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The destination isn't managed content, so a failure removing it leaves it, without records, and reports nothing:
    # the binding is removed all the same.
    with incremental.unmanaged_user(tmp_path) as scene:
        handle = _synchronized(bindings, scene.root_layer_path)
        destination = bpy.data.collections["Shot"]
        _fail_removing(monkeypatch, lambda d: d == destination)
        result = handle.remove()
        assert (result.state, result.diagnostics, result.pending_cleanup_diagnostics) == (ResultState.SUCCESS, (), ())
        assert (list(destination.objects), id_property_records.keys(destination)) == ([], [])
        assert bindings.in_scene(_scene()) == []
        assert _ledger() == {}


def test_undo_restores_the_records_on_a_destination_that_stayed(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # UNDO-08: with an unmanaged object linked into the destination, which stays, undo restores the binding's records
    # and content on it, and redo removes them again, leaving the collection and the object.
    undo.require_global_undo()
    monkeypatch.setattr(api, "_undo_steps_enabled", lambda: True)
    with incremental.unmanaged_user(tmp_path) as scene:
        handle = _synchronized(bindings, scene.root_layer_path)
        bpy.data.collections["Shot"].objects.link(bpy.data.objects.new("Visitor", None))
        managed = {_key(d) for d in _managed(handle).values()}
        undo.push("base")
        names = _names()
        records = sorted(id_property_records.keys(bpy.data.collections["Shot"]))
        assert handle.remove().state is ResultState.SUCCESS
        undo.undo()
        assert (_names(), bindings.in_scene(_scene())) == (names, [handle])
        assert sorted(id_property_records.keys(bpy.data.collections["Shot"])) == records
        assert {_key(d) for d in _managed(handle).values()} == managed
        undo.redo()
        assert bindings.in_scene(_scene()) == []
        destination = bpy.data.collections["Shot"]
        assert ([o.name for o in destination.objects], id_property_records.keys(destination)) == (["Visitor"], [])
        assert not managed & _names()
