"""Resource stability on full rebuilds (lifecycle.md#resource-stability), and unmanaged users of managed content.

On F-NO-OP-REFRESH, one drawn copy of each kind M7 draws, synchronized again unchanged, each time a requested full
rebuild, so every partition is replaced, and on F-UNMANAGED-USER, whose managed content a test gives unmanaged users
before rebuilding, or before its edit and a refresh (lifecycle.md#ownership-and-lifecycle). Counts are by kind of
managed resource: active ones are in the binding's manifest, with each object linked into the destination; pending ones
are the ledger's; one released intact is in neither. Failures are injected by patching the removal module's function, so
src/ has no hooks. An unchanged refresh, which replaces nothing, is test_incremental_refresh.py's.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy
from pxr import Gf

from fixtures import incremental
from proscenium_sync.binding_persistence import id_property_records
from proscenium_sync.binding_persistence.manifests import RepresentationRole
from proscenium_sync.binding_runtime import ownership, pending_cleanup
from proscenium_sync.results import DiagnosticCode, ResultState
from proscenium_sync.synchronization import datablock_removal
from support.blend import prim_name
from support.usd import binding_on_file

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    import pytest

    from proscenium_sync.api.bindings import BindingHandle, Bindings
    from proscenium_sync.binding_persistence import manifests
    from proscenium_sync.binding_persistence.cleanup_ledgers import LedgerEntry
    from proscenium_sync.results import Diagnostic, Result

SYNCHRONIZATIONS = 5  # STAB-01's unchanged synchronizations
FAILING = "Plain"  # F-NO-OP-REFRESH's mesh whose object and bounds mesh retirement fails to remove


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _destination() -> bpy.types.Collection:
    return bpy.data.collections["Shot"]


def _manifest(handle: BindingHandle) -> manifests.Manifest:
    manifest = ownership.manifest(handle.binding_id)
    assert isinstance(manifest, id_property_records.LoadedRecord)
    return manifest.record


def _ledger(handle: BindingHandle) -> dict[str, LedgerEntry]:
    ledger = pending_cleanup.ledger()
    assert not isinstance(ledger, id_property_records.RefusedRecord)
    entries = {} if ledger is None else ledger.record.entries
    return {k: e for k, e in entries.items() if e.binding_id == handle.binding_id}


@dataclass(frozen=True)
class ResourceCounts:
    """A binding's managed resources by role: active in its manifest, and pending in the ledger."""

    active: Counter[RepresentationRole]
    pending: Counter[RepresentationRole]


def _counts(handle: BindingHandle) -> ResourceCounts:
    entries = _manifest(handle).entries.values()
    linked = set(_destination().objects)
    for entry in entries:  # each active object is displayed: linked into the destination
        assert entry.datablock is not None and id_property_records.alive(entry.datablock)
        if entry.role in (RepresentationRole.OBJECT, RepresentationRole.SHEAR_PARENT):
            assert entry.datablock in linked, entry
    return ResourceCounts(Counter(e.role for e in entries), Counter(e.role for e in _ledger(handle).values()))


def _datablocks() -> Counter[str]:
    """The file's objects and meshes, by kind."""
    return Counter({"objects": len(bpy.data.objects), "meshes": len(bpy.data.meshes)})


def _content(diagnostics: Sequence[Diagnostic]) -> list[tuple[object, ...]]:
    """The source and display diagnostics, which an unchanged synchronization keeps (DIAG-07)."""
    return sorted(
        (d.code, d.source_path, d.message)
        for d in diagnostics
        if d.code not in (DiagnosticCode.RETIREMENT_FAILED, DiagnosticCode.DISPOSAL_FAILED)
    )


def _failing_removal(monkeypatch: pytest.MonkeyPatch, failing: Callable[[bpy.types.ID], bool]) -> None:
    """Make removing a datablock failing accepts fail, and so any call removing one."""
    remove = datablock_removal._batch_remove  # noqa: SLF001 - the step's module function

    def failing_remove(datablocks: Sequence[bpy.types.ID]) -> None:
        if any(failing(d) for d in datablocks):
            raise RuntimeError("injected failure")
        remove(datablocks)

    monkeypatch.setattr(datablock_removal, "_batch_remove", failing_remove)


def _synchronized(bindings: Bindings, root: Path) -> tuple[BindingHandle, Result]:
    handle = binding_on_file(bindings, _scene(), root, name="Shot")
    return handle, handle.synchronize(0)


# --- F-NO-OP-REFRESH -----------------------------------------------------------------------------------------


def test_unchanged_synchronizations_keep_their_counts(bindings: Bindings, tmp_path: Path) -> None:
    # STAB-01 on F-NO-OP-REFRESH "unchanged", each a full rebuild: the active count by role, the file's managed
    # datablocks, and the source and display diagnostics stay the first synchronization's, and nothing is pending.
    with incremental.no_op_refresh(tmp_path) as scene:
        handle, first = _synchronized(bindings, scene.root_layer_path)
        assert first.state is ResultState.COMPLETED_WITH_ISSUES  # its placeholders warn
        clean, datablocks = _counts(handle), _datablocks()
        assert clean.active[RepresentationRole.OBJECT] == len(scene.copies)
        assert clean.pending == Counter()
        for _ in range(SYNCHRONIZATIONS - 1):
            result = handle.synchronize(0, full_rebuild=True)
            assert (_counts(handle), _datablocks()) == (clean, datablocks)
            assert _content(result.diagnostics) == _content(first.diagnostics)
            assert result.pending_cleanup_diagnostics == ()


def test_failed_retirement_adds_only_tracked_inactive_leftovers(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # STAB-02 on F-NO-OP-REFRESH "disposal-failure": each full rebuild fails to retire Plain's object and bounds mesh.
    # The active count stays the clean one; each leftover is linked into no scene, in the ledger with its ownership
    # evidence, and reported by one cleanup diagnostic; the file gains only the leftovers.
    with incremental.no_op_refresh(tmp_path) as scene:
        handle, _ = _synchronized(bindings, scene.root_layer_path)
        clean, datablocks = _counts(handle), _datablocks()
        _failing_removal(monkeypatch, lambda d: prim_name(d) == FAILING)
        for rebuild in range(1, SYNCHRONIZATIONS):
            result = handle.synchronize(0, full_rebuild=True)
            counts = _counts(handle)
            assert counts.active == clean.active
            assert counts.pending == Counter(
                {RepresentationRole.OBJECT: rebuild, RepresentationRole.BOUNDS_MESH: rebuild}
            )
            assert _datablocks() == datablocks + Counter({"objects": rebuild, "meshes": rebuild})
            ledger = _ledger(handle)
            for ledger_key, entry in ledger.items():
                assert entry.datablock is not None and prim_name(entry.datablock) == FAILING
                assert not entry.datablock.users_scene if isinstance(entry.datablock, bpy.types.Object) else True
                assert (entry.binding_id, entry.diagnostic.pending_resource_key) == (handle.binding_id, ledger_key)
            reported = [d for d in result.diagnostics if d.code is DiagnosticCode.RETIREMENT_FAILED]
            assert len(reported) == 2  # this rebuild's own leftovers, each once
            assert set(result.pending_cleanup_diagnostics) == {e.diagnostic for e in ledger.values()}


def test_a_retry_restores_the_clean_counts(bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # STAB-03 on F-NO-OP-REFRESH "cleanup-retry": with the failure gone, a retry removes every leftover, so the
    # file's managed datablocks are the published generation's clean baseline, and no cleanup diagnostic is left.
    with incremental.no_op_refresh(tmp_path) as scene:
        handle, _ = _synchronized(bindings, scene.root_layer_path)
        datablocks = _datablocks()
        with monkeypatch.context() as failing:
            _failing_removal(failing, lambda d: prim_name(d) == FAILING)
            for _ in range(2):
                handle.synchronize(0, full_rebuild=True)
        assert _ledger(handle)
        result = handle.retry_cleanup()
        assert (result.state, result.diagnostics, result.pending_cleanup_diagnostics) == (ResultState.SUCCESS, (), ())
        assert _ledger(handle) == {}
        assert _datablocks() == datablocks


def test_a_resource_with_an_unmanaged_user_is_released_and_counted_apart(bindings: Bindings, tmp_path: Path) -> None:
    # STAB-04 on F-NO-OP-REFRESH "protected-user": Plain's bounds mesh, given to an unmanaged object, is released
    # intact by the full rebuild, in neither the manifest nor the ledger, and survives a retry; the active and pending
    # counts are the clean ones without it.
    with incremental.no_op_refresh(tmp_path) as scene:
        handle, _ = _synchronized(bindings, scene.root_layer_path)
        clean = _counts(handle)
        [mesh] = (
            e.datablock
            for e in _manifest(handle).entries.values()
            if e.role is RepresentationRole.BOUNDS_MESH and e.source_entity_paths[0] == "/World/Plain"
        )
        assert isinstance(mesh, bpy.types.Mesh)
        vertices = [v.co[:] for v in mesh.vertices]
        user = bpy.data.objects.new("Mine", mesh)
        _scene().collection.objects.link(user)
        handle.synchronize(0, full_rebuild=True)
        assert _counts(handle) == clean
        assert mesh not in {e.datablock for e in _manifest(handle).entries.values()}
        assert handle.retry_cleanup().state is ResultState.SUCCESS
        assert (user.data, [v.co[:] for v in mesh.vertices]) == (mesh, vertices)
        assert _counts(handle) == clean


# --- F-UNMANAGED-USER ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class UnmanagedState:
    """What an unmanaged object holds that a refresh must leave as it was (OWN-07)."""

    name: str
    data: object
    matrix_basis: tuple[tuple[float, ...], ...]
    parent: object
    collections: frozenset[str]
    selected: bool

    @staticmethod
    def of(obj: bpy.types.Object) -> UnmanagedState:
        return UnmanagedState(
            obj.name,
            obj.data,
            tuple(tuple(obj.matrix_basis[r][c] for c in range(4)) for r in range(4)),
            obj.parent,
            frozenset(c.name for c in obj.users_collection),
            obj.select_get(),
        )


def _managed(handle: BindingHandle, source: str, role: RepresentationRole) -> bpy.types.ID:
    [found] = (
        e.datablock for e in _manifest(handle).entries.values() if e.role is role and e.source_entity_paths[0] == source
    )
    assert found is not None
    return found


def _unmanaged_users(handle: BindingHandle) -> dict[str, bpy.types.Object]:
    """F-UNMANAGED-USER's users: Used's bounds mesh on an object, Child's object under an empty, and a visitor."""
    mesh = _managed(handle, incremental.USED, RepresentationRole.BOUNDS_MESH)
    child = _managed(handle, incremental.CHILD, RepresentationRole.OBJECT)
    assert isinstance(mesh, bpy.types.Mesh) and isinstance(child, bpy.types.Object)
    mine, rig, visitor = (
        bpy.data.objects.new("Mine", mesh),
        bpy.data.objects.new("Rig", None),
        bpy.data.objects.new("Visitor", None),
    )
    for obj in (mine, rig):
        _scene().collection.objects.link(obj)
    _destination().objects.link(visitor)
    child.parent = rig
    mine.select_set(True)
    return {"mine": mine, "rig": rig, "visitor": visitor}


def test_a_full_rebuild_leaves_unmanaged_users_as_they_were(bindings: Bindings, tmp_path: Path) -> None:
    # OWN-07, OWN-08, STAB-04 on F-UNMANAGED-USER "full-rebuild": synchronized again, the unmanaged objects keep their
    # data, transforms, parenting, links, selection, and names; Used's old bounds mesh, which one uses, keeps its name
    # and vertices, released intact and counted apart, and Used's copy gets a new one.
    with incremental.unmanaged_user(tmp_path) as scene:
        handle, _ = _synchronized(bindings, scene.root_layer_path)
        clean = _counts(handle)
        users = _unmanaged_users(handle)
        before = {key: UnmanagedState.of(obj) for key, obj in users.items()}
        mesh = users["mine"].data
        assert isinstance(mesh, bpy.types.Mesh)
        name, vertices = mesh.name, [v.co[:] for v in mesh.vertices]
        assert handle.synchronize(0, full_rebuild=True).state is not ResultState.FATAL_FAILURE
        assert {key: UnmanagedState.of(obj) for key, obj in users.items()} == before
        assert (mesh.name, [v.co[:] for v in mesh.vertices]) == (name, vertices)
        assert _managed(handle, incremental.USED, RepresentationRole.BOUNDS_MESH) != mesh
        assert _counts(handle) == clean
        assert _ledger(handle) == {}


def test_an_edit_rebuilds_a_partition_unmanaged_content_uses(bindings: Bindings, tmp_path: Path) -> None:
    # OWN-07, OWN-08, STAB-04, CHG-06, CHG-14, CHG-17 on F-UNMANAGED-USER "used-mesh-changed": after the edit, a
    # refresh rebuilds Used's partition as a new object and bounds mesh, since an unmanaged object uses its old mesh,
    # which keeps its name and vertices, released intact; Child's object, which nothing else uses, is kept and moved
    # under its unmanaged parent; the unmanaged objects are as they were.
    with incremental.unmanaged_user(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        assert handle.attach(scene.stage).state is ResultState.SUCCESS  # the stage the edit changes
        assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        clean = _counts(handle)
        users = _unmanaged_users(handle)
        before = {key: UnmanagedState.of(obj) for key, obj in users.items()}
        used = _managed(handle, incremental.USED, RepresentationRole.OBJECT)
        child = _managed(handle, incremental.CHILD, RepresentationRole.OBJECT)
        mesh = users["mine"].data
        assert isinstance(mesh, bpy.types.Mesh) and isinstance(child, bpy.types.Object)
        name, vertices = mesh.name, [v.co[:] for v in mesh.vertices]
        scene.edit()
        assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        assert {key: UnmanagedState.of(obj) for key, obj in users.items()} == before
        assert (mesh.name, [v.co[:] for v in mesh.vertices]) == (name, vertices)
        assert _managed(handle, incremental.USED, RepresentationRole.OBJECT) != used
        assert _managed(handle, incremental.USED, RepresentationRole.BOUNDS_MESH) != mesh
        assert _managed(handle, incremental.CHILD, RepresentationRole.OBJECT) == child
        assert child.parent == users["rig"]
        assert Gf.IsClose(Gf.Vec3d(*child.matrix_world.translation[:]), scene.edited_child_translation, 1e-6)
        assert _counts(handle) == clean
        assert _ledger(handle) == {}


def test_a_retry_releases_a_leftover_given_an_unmanaged_user(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PEND-02, STAB-04 on F-UNMANAGED-USER "cleanup-retry": a full rebuild fails to retire Used's old bounds mesh, which
    # an unmanaged object is then given; the retry releases it intact and resolves its tracking.
    with incremental.unmanaged_user(tmp_path) as scene:
        handle, _ = _synchronized(bindings, scene.root_layer_path)
        mesh = _managed(handle, incremental.USED, RepresentationRole.BOUNDS_MESH)
        with monkeypatch.context() as failing:
            _failing_removal(failing, lambda d: d == mesh)
            handle.synchronize(0, full_rebuild=True)
        [entry] = _ledger(handle).values()
        assert entry.datablock == mesh
        user = bpy.data.objects.new("Mine", mesh)
        _scene().collection.objects.link(user)
        assert handle.retry_cleanup().state is ResultState.SUCCESS
        assert user.data == mesh and id_property_records.alive(mesh)
        assert _ledger(handle) == {}
