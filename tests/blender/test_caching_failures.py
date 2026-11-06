"""Cache calls that fail, against the stub application layer (pipeline.md#cached-time-codes; M5 plan, E2).

On F-CACHED-TIME-CODES (fixtures/transaction.py): synchronized at 0, with 5, 10, and 20 cached, a call for 15 fails at
keying, its failure step, or while recording what it cached. Each failure is injected by patching a module function the
call reaches, so src/ has no hooks, and each test compares the whole published generation, every action's keys, and
the file's datablocks before and after (published.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest
from pxr import Usd

from fixtures import transaction
from fixtures.transaction import Step, translation
from proscenium.binding.persistence import binding_state, ledgers, records
from proscenium.binding.persistence.manifests import RepresentationRole
from proscenium.binding.results import DiagnosticCode, ResultState
from proscenium.binding.runtime import ownership, pending_cleanup
from proscenium.binding.source_access.stages import PayloadPolicy
from proscenium.synchronization import application, removal

from .published import datablocks, published_generation

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from fixtures.transaction import CachedTimeCodesScene
    from proscenium.api.bindings import BindingHandle, Bindings

MOVER = "/World/Mover"
PLACEHOLDERS = len(transaction.DRAWN[PayloadPolicy.LOAD_ALL])  # each keyed once per time code


def _synchronized(bindings: Bindings, scene: CachedTimeCodesScene) -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
    assert handle.attach(scene.caller).state is ResultState.SUCCESS
    assert handle.synchronize(scene.synchronized).state is ResultState.SUCCESS
    return handle


def _keys() -> dict[tuple[int, str, int], list[tuple[float, ...]]]:
    """Every action's keys, by action, property, and index."""
    return {
        (action.session_uid, fcurve.data_path, fcurve.array_index): [tuple(p.co[:]) for p in fcurve.keyframe_points]
        for action in bpy.data.actions
        for layer in action.layers
        for strip in layer.strips
        if isinstance(strip, bpy.types.ActionKeyframeStrip)
        for channelbag in strip.channelbags
        for fcurve in channelbag.fcurves
    }


def _held(handle: BindingHandle) -> tuple[Any, ...]:
    """What a failing call must leave as it was: the generation, the last attempt, the keys, and the datablocks."""
    destination = bpy.data.collections["Shot"]
    attempt = records.stored(destination, binding_state.ATTEMPT_KEY)
    return published_generation(handle.binding_id, destination), attempt, _keys(), datablocks()


def _failing_keying(monkeypatch: pytest.MonkeyPatch, after: int) -> None:
    """Make keying fail once after-many placeholders are keyed at a time code."""
    insert = application._insert_keys  # noqa: SLF001 - the step's module function
    calls: list[None] = []

    def failing(*args: Any) -> None:
        if len(calls) == after:
            raise RuntimeError("injected keying failure")
        calls.append(None)
        insert(*args)

    monkeypatch.setattr(application, "_insert_keys", failing)


def _shown_at(handle: BindingHandle, frame: float) -> tuple[float, ...]:
    bpy.data.scenes["Scene"].frame_set(int(frame))
    manifest = ownership.manifest(handle.binding_id)
    assert isinstance(manifest, records.Loaded)
    [obj] = [
        e.datablock
        for e in manifest.record.entries.values()
        if e.role is RepresentationRole.OBJECT and e.covers == (MOVER,)
    ]
    assert isinstance(obj, bpy.types.Object)
    return tuple(obj.matrix_world.translation[:])


@pytest.mark.parametrize("after", [0, 1, PLACEHOLDERS - 1])
def test_a_failing_call_caches_none_of_its_time_codes(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after: int
) -> None:
    # CACHE-03, CACHE-11 on F-CACHED-TIME-CODES "failed-call": failing at keying, after each number of placeholders
    # keyed, the call returns its own failure and leaves the generation, its keys, and the last attempt as they were;
    # the frame of the failed time code still shows the latest cached before it.
    with transaction.cached_time_codes(tmp_path) as scene:
        assert scene.failure is Step.PREPARE
        handle = _synchronized(bindings, scene)
        assert handle.cache(scene.cached).state is ResultState.SUCCESS
        before = _held(handle)
        with monkeypatch.context() as patch:
            _failing_keying(patch, after)
            result = handle.cache(scene.failing)
        assert [d.code for d in result.diagnostics] == [DiagnosticCode.PREPARATION_FAILED]
        assert result.time_codes == tuple(Usd.TimeCode(t) for t in scene.failing)
        assert _held(handle) == before
        assert pending_cleanup.nothing_pending(handle.binding_id)
        [failed] = scene.failing
        latest = max(t for t in (scene.synchronized, *scene.cached) if t < failed)
        assert _shown_at(handle, failed) == pytest.approx(translation(MOVER, latest))
        assert handle.cache(scene.failing).state is ResultState.SUCCESS  # nothing left behind to stop it
        assert _shown_at(handle, failed) == pytest.approx(translation(MOVER, failed))


def test_a_failing_first_call_disposes_of_the_actions_it_made(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CACHE-03: a first call makes each object's action, so failing partway it disposes of them, and the objects have
    # no animation data again.
    with transaction.cached_time_codes(tmp_path) as scene:
        handle = _synchronized(bindings, scene)
        before = _held(handle)
        _failing_keying(monkeypatch, 2 * 2)  # the own and cached time codes' keys, of two placeholders
        assert handle.cache(scene.cached[:1]).state is ResultState.FATAL_FAILURE
        assert _held(handle) == before
        assert not bpy.data.actions
        assert all(o.animation_data is None for o in bpy.data.collections["Shot"].objects)


def _failing_write(*_args: object) -> None:
    raise RuntimeError("injected record failure")


@pytest.mark.parametrize(
    ("module", "name"),
    [(ownership, "set_manifest_entries"), (binding_state, "write_generation")],
    ids=["manifest", "generation"],
)
def test_a_failing_record_write_undoes_the_keys(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: Any, name: str
) -> None:
    # CACHE-03: recording a first call's time codes failing, after every key is in, removes them, restores the
    # manifest without the actions it made, and disposes of them.
    with transaction.cached_time_codes(tmp_path) as scene:
        handle = _synchronized(bindings, scene)
        before = _held(handle)
        with monkeypatch.context() as patch:
            patch.setattr(module, name, _failing_write)
            result = handle.cache(scene.cached)
        assert [d.code for d in result.diagnostics] == [DiagnosticCode.PUBLICATION_FAILED]
        assert _held(handle) == before
        assert not bpy.data.actions


def test_an_action_that_cant_be_disposed_of_is_pending_cleanup(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CACHE-03, under the transaction's rules: an action whose disposal fails enters the ledger, retryable, from the
    # cache call, with a pending-cleanup diagnostic in its result, and nothing it keyed stays shown.
    with transaction.cached_time_codes(tmp_path) as scene:
        handle = _synchronized(bindings, scene)
        shown = _shown_at(handle, scene.cached[-1])
        remove = removal._batch_remove  # noqa: SLF001 - the step's module function

        def failing_remove(datablocks: Sequence[bpy.types.ID]) -> None:
            if any(isinstance(d, bpy.types.Action) for d in datablocks):
                raise RuntimeError("injected disposal failure")
            remove(datablocks)

        with monkeypatch.context() as patch:
            _failing_keying(patch, PLACEHOLDERS + 1)
            patch.setattr(removal, "_batch_remove", failing_remove)
            result = handle.cache(scene.cached)
        codes = [d.code for d in result.diagnostics]
        assert codes == [DiagnosticCode.PREPARATION_FAILED, *[DiagnosticCode.DISPOSAL_FAILED] * (len(codes) - 1)]
        ledger = pending_cleanup.ledger()
        assert isinstance(ledger, records.Loaded)
        entries = list(ledger.record.entries.values())
        assert len(entries) == len(codes) - 1 >= 1
        assert {(e.role, e.operation) for e in entries} == {
            (RepresentationRole.ACTION, ledgers.OriginatingOperation.CACHE)
        }
        assert all(o.animation_data is None for o in bpy.data.collections["Shot"].objects)
        assert _shown_at(handle, scene.cached[-1]) == shown
        assert handle.retry_cleanup().state is ResultState.SUCCESS
        assert not bpy.data.actions
