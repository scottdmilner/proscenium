"""Failures only application can detect abort the attempt (pipeline.md#blender-application), on F-APPLICATION-FAILURE.

Each failure comes once the fixture's count of resources is prepared, by each of ApplicationFailureKind in turn, on a
first synchronization and a later one. A runtime failure is a Blender operation making a datablock raising: Blender's
collections can't be patched, so the test hands the application layer a stand-in for bpy whose meshes and objects
collections raise on the next new datablock. A state change removes the destination collection while preparation
continues. The plan authorizes no fallback, so each is fatal (APP-06), with one diagnostic naming its kind and where
it came from (APP-05).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import bpy
import pytest
from pxr import Sdf

from fixtures import transaction
from fixtures.transaction import DRAWN, ApplicationFailureKind
from proscenium_sync.bindings import binding_service as bindings_module
from proscenium_sync.results import DiagnosticCode, ResultState
from proscenium_sync.runtime import pending_cleanup
from proscenium_sync.source_access.binding_settings import PayloadPolicy
from proscenium_sync.synchronization import application, preparation_resources

from .published_state import datablocks, published_generation

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from proscenium_sync.bindings import BindingHandle, Bindings
    from proscenium_sync.persistence.manifests import RepresentationRole

Attempt = tuple[ApplicationFailureKind, bool]  # its kind, and whether a generation was published before
ATTEMPTS = [(kind, later) for kind in ApplicationFailureKind for later in (False, True)]


def _ids(attempt: Attempt) -> str:
    kind, later = attempt
    return f"{kind.value.replace(' ', '-')}-{'later' if later else 'first'}"


class _FailingDatablocks:
    """A bpy.data collection whose new raises once the shared count of datablocks made reaches its limit."""

    def __init__(self, collection: Any, made: list[None], limit: int) -> None:
        self._collection, self._made, self._limit = collection, made, limit

    def new(self, *args: object) -> bpy.types.ID:
        if len(self._made) == self._limit:
            raise RuntimeError("injected resource failure")
        self._made.append(None)
        return self._collection.new(*args)

    def __getattr__(self, name: str) -> object:
        return getattr(self._collection, name)

    def __reversed__(self) -> Iterator[bpy.types.ID]:
        return reversed(self._collection)


class _BpyWithFailingDatablocks:
    """bpy as the application layer reads it, its meshes and objects failing past the limit."""

    def __init__(self, limit: int) -> None:
        made: list[None] = []
        self.data = SimpleNamespace(
            meshes=_FailingDatablocks(bpy.data.meshes, made, limit),
            objects=_FailingDatablocks(bpy.data.objects, made, limit),
        )
        self.types = bpy.types


def _inject_runtime_failure(monkeypatch: pytest.MonkeyPatch, prepared: int, _destination: bpy.types.Collection) -> None:
    monkeypatch.setattr(application, "bpy", _BpyWithFailingDatablocks(prepared))


def _inject_state_change(monkeypatch: pytest.MonkeyPatch, prepared: int, destination: bpy.types.Collection) -> None:
    track = preparation_resources.PreparationResources.track
    held: list[None] = []

    def removing(
        work: preparation_resources.PreparationResources, entry_key: str, role: RepresentationRole, d: bpy.types.ID
    ) -> None:
        track(work, entry_key, role, d)
        held.append(None)
        if len(held) == prepared:
            bpy.data.collections.remove(destination)

    monkeypatch.setattr(preparation_resources.PreparationResources, "track", removing)


INJECT: dict[ApplicationFailureKind, Callable[[pytest.MonkeyPatch, int, bpy.types.Collection], None]] = {
    ApplicationFailureKind.RUNTIME: _inject_runtime_failure,
    ApplicationFailureKind.STATE_CHANGE: _inject_state_change,
}


def _binding(bindings: Bindings, scene: transaction.ApplicationFailureScene) -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
    assert handle.attach(scene.caller).state is ResultState.SUCCESS
    return handle


@pytest.mark.parametrize("attempt", ATTEMPTS, ids=_ids)
def test_an_application_failure_aborts_the_attempt(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attempt: Attempt
) -> None:
    # APP-05, APP-06 on F-APPLICATION-FAILURE "runtime" and "state-change".
    kind, later = attempt
    pushed: list[str] = []
    monkeypatch.setattr(bindings_module, "_push_undo", pushed.append)
    with transaction.application_failure(tmp_path) as scene:
        handle = _binding(bindings, scene)
        if later:
            assert handle.synchronize(0).state is ResultState.SUCCESS
        destination = bpy.data.collections["Shot"]
        published, before = published_generation(handle.binding_id, destination), datablocks()
        removed = ("Collection", destination.session_uid)
        pushed.clear()
        INJECT[kind](monkeypatch, scene.prepared_before_failure, destination)
        result = handle.synchronize(10, full_rebuild=True)  # every partition prepared, as on a first one
        assert result.state is scene.outcome
        [diagnostic] = result.diagnostics
        assert not pushed
        if kind is ApplicationFailureKind.RUNTIME:
            # The fifth datablock is the third copy's bounds mesh, in the plan's order, which is the paths'.
            third = sorted(DRAWN[PayloadPolicy.LOAD_ALL], key=Sdf.Path)[2]
            assert (diagnostic.code, diagnostic.source_path, diagnostic.role) == (
                DiagnosticCode.PREPARATION_FAILED,
                third,
                "bounds mesh",
            )
            assert published_generation(handle.binding_id, destination) == published
            assert datablocks() == before
            assert pending_cleanup.nothing_pending(handle.binding_id)
        else:
            assert diagnostic.code is DiagnosticCode.DESTINATION_INVALID
            assert "'Shot'" in diagnostic.message
            # Everything prepared is gone; what was published stays, with only the destination removed.
            assert datablocks() == before - {removed}
            assert pending_cleanup.nothing_pending(handle.binding_id)
