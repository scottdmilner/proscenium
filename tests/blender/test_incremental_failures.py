"""Failures injected on the incremental path, after preparation (TXN-12; M7 plan, C7).

On F-EDIT-SEQUENCE, cached at its time codes and shown at the last, one refresh would update kept copies in place
(Odd moved, grown, and made invisible; Mover's cached keys removed), rebuild A's partition for a shear, build Dormant's,
and retire B's. A failure injected after everything is prepared, after the local updates are made, at the manifest's
write, or at the generation record's leaves the published generation as it was (published_state.py), every kept
object's transform, hide flags, bounds mesh, and action as before, and the prepared work disposed of; when disposal
fails too, what it couldn't remove is tracked pending cleanup, linked into no scene. Each failure patches a module
function the transaction calls, so src/ has no hooks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest
from pxr import Gf, UsdGeom, Vt

from fixtures import edit_sequence
from proscenium_sync.binding_persistence import binding_state, id_property_records, manifests
from proscenium_sync.binding_runtime import pending_cleanup
from proscenium_sync.results import DiagnosticCode, ResultState
from proscenium_sync.synchronization import datablock_removal, local_updates

from .published_state import datablocks, published_generation

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from pxr import Usd

    from proscenium_sync.api.bindings import BindingHandle, Bindings


def _raising_after(function: Callable[..., Any]) -> Callable[..., Any]:
    """function, made to raise once it has done its work."""

    def raising(*args: Any, **kwargs: Any) -> Any:
        function(*args, **kwargs)
        raise RuntimeError("injected failure")

    return raising


def _raising_once(function: Callable[..., Any]) -> Callable[..., Any]:
    """function, made to raise on its first call alone, so undoing it with another call succeeds."""
    calls: list[None] = []

    def raising(*args: Any, **kwargs: Any) -> Any:
        calls.append(None)
        if len(calls) == 1:
            raise RuntimeError("injected failure")
        return function(*args, **kwargs)

    return raising


# Each injection point: the module and function patched, how, and the failure's diagnostic.
_FAILURES = {
    "after-preparation": (local_updates, "prepare_updates", _raising_after, DiagnosticCode.PREPARATION_FAILED),
    "after-local-updates": (local_updates, "apply_updates", _raising_after, DiagnosticCode.PUBLICATION_FAILED),
    "manifest-write": (manifests, "write_manifest_entries", _raising_once, DiagnosticCode.PUBLICATION_FAILED),
    "generation-write": (binding_state, "write_generation", _raising_once, DiagnosticCode.PUBLICATION_FAILED),
}


def _edit(stage: Usd.Stage) -> None:
    """Edit the live stage so one refresh makes every kind of change on the incremental path."""
    odd = stage.GetPrimAtPath(edit_sequence.ODD)
    stage.GetAttributeAtPath(f"{edit_sequence.ODD}.xformOp:translate").Set(Gf.Vec3d(7, 0, 0))
    UsdGeom.Boundable(odd).GetExtentAttr().Set([Gf.Vec3f(0, 0, 0), Gf.Vec3f(2, 2, 2)])
    UsdGeom.Imageable(odd).MakeInvisible()
    ops = stage.GetAttributeAtPath(f"{edit_sequence.A}.xformOpOrder")
    ops.Set(Vt.TokenArray(["xformOp:translate", "xformOp:transform"]))  # a shear: A's partition rebuilt
    stage.GetPrimAtPath(edit_sequence.DORMANT).SetActive(True)  # built
    stage.GetPrimAtPath(edit_sequence.B).SetActive(False)  # retired


def _kept_state(destination: bpy.types.Collection) -> dict[int, tuple[object, ...]]:
    """What a refresh would change of each published object: transform components, hide flags, data, and action."""
    return {
        obj.session_uid: (
            obj.location[:],
            obj.rotation_euler[:],
            obj.scale[:],
            obj.hide_viewport,
            obj.hide_render,
            obj.data,
            None if obj.animation_data is None else obj.animation_data.action,
        )
        for obj in destination.objects
    }


def _published(handle: BindingHandle, destination: bpy.types.Collection) -> dict[str, Any]:
    """The published generation, its objects' world matrices evaluated from what they store (published_state.py).

    A world matrix is derived: Blender computes it again from an object's transform and animation at a depsgraph
    update, so one an undone local update set reads stale until then.
    """
    view_layer = bpy.data.scenes["Scene"].view_layers[0]
    view_layer.update()
    return published_generation(handle.binding_id, destination)


def _cached(bindings: Bindings, scene: edit_sequence.EditSequenceScene) -> BindingHandle:
    """A binding synchronized at 0, its time codes cached, and the last shown."""
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
    assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
    assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
    assert handle.cache(scene.cached_time_codes).state is not ResultState.FATAL_FAILURE
    bpy.data.scenes["Scene"].frame_set(int(scene.cached_time_codes[-1]))
    return handle


@pytest.mark.parametrize("failure", list(_FAILURES))
def test_a_failure_after_preparation_leaves_the_generation_as_it_was(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    # TXN-12, CHG-05 on F-EDIT-SEQUENCE "publication-failure".
    module, name, inject, code = _FAILURES[failure]
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _cached(bindings, scene)
        destination = bpy.data.collections["Shot"]
        published, kept, before = (
            _published(handle, destination),
            _kept_state(destination),
            datablocks(),
        )
        _edit(scene.stage)
        with monkeypatch.context() as patch:
            patch.setattr(module, name, inject(getattr(module, name)))
            result = handle.synchronize(0)
        assert result.state is ResultState.FATAL_FAILURE
        assert [d.code for d in result.diagnostics if d.code is code] == [code], result.diagnostics
        assert _kept_state(destination) == kept  # before an update evaluates the restored keys again
        assert _published(handle, destination) == published
        assert datablocks() == before
        assert pending_cleanup.nothing_pending(handle.binding_id)
        # The next refresh, with nothing failing, makes the changes.
        assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        assert _published(handle, destination) != published


def test_prepared_work_disposal_couldnt_remove_is_tracked(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # TXN-12: the manifest's write failing, and disposal failing to remove what was prepared, leaves the generation as
    # it was and every datablock the attempt made tracked pending cleanup, linked into no scene.
    def failing_remove(_removed: Sequence[bpy.types.ID]) -> None:
        raise RuntimeError("injected disposal failure")

    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _cached(bindings, scene)
        destination = bpy.data.collections["Shot"]
        published, kept, before = _published(handle, destination), _kept_state(destination), datablocks()
        _edit(scene.stage)
        with monkeypatch.context() as patch:
            patch.setattr(manifests, "write_manifest_entries", _raising_once(manifests.write_manifest_entries))
            patch.setattr(datablock_removal, "_batch_remove", failing_remove)
            result = handle.synchronize(0)
        assert result.state is ResultState.FATAL_FAILURE
        codes = {d.code for d in result.diagnostics}
        assert DiagnosticCode.PUBLICATION_FAILED in codes and DiagnosticCode.DISPOSAL_FAILED in codes
        assert _kept_state(destination) == kept  # before an update evaluates the restored keys again
        assert _published(handle, destination) == published
        ledger = pending_cleanup.ledger()
        assert isinstance(ledger, id_property_records.LoadedRecord)
        left = {d for e in ledger.record.entries.values() if (d := e.datablock) is not None}
        assert left and {(type(d).__name__, d.session_uid) for d in left} == datablocks() - before
        assert not any(obj in left for target in bpy.data.scenes for obj in target.objects)
        assert handle.retry_cleanup().state is ResultState.SUCCESS
