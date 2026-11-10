"""Calls made while a synchronization, a cache call, or a cleanup retry runs (source-access.md#source-consistency).

M5 plan, D11 and E1. On F-SOURCE-CHANGE (fixtures/transaction.py), with a second binding on the same stage. The calls
are made from inside
the evaluation step, by patching the core's SceneIndexChain, and from inside a retry's removal, by patching the removal
module's function, so src/ has no hooks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest

from fixtures import transaction
from proscenium import synchronization
from proscenium.api.bindings import ReentrantCallError
from proscenium.binding.persistence import binding_records, binding_state, id_property_records
from proscenium.binding.results import ResultState
from proscenium.binding.source_access.binding_settings import PayloadPolicy
from proscenium.core import _core
from proscenium.synchronization import datablock_removal
from support.destinations import destination

from .transaction_failures import failing_preparation

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from pxr import Usd

    from fixtures.transaction import TransactionScene
    from proscenium.api.bindings import BindingHandle, Bindings


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _binding(bindings: Bindings, scene: TransactionScene, name: str) -> BindingHandle:
    handle = bindings.create_binding(_scene(), name=name)
    assert handle.attach(scene.caller).state is ResultState.SUCCESS
    return handle


def _held(bindings: Bindings, handles: Sequence[BindingHandle]) -> tuple[Any, ...]:
    """The bindings' records, stages, and the file's datablocks, by what a call could change."""
    stored = [id_property_records.stored(_scene(), binding_records.config_key(h.binding_id)) for h in handles]
    stored += [
        id_.get(id_property_records.NAMESPACE) for id_ in (*bpy.data.collections, *binding_records.index_texts())
    ]
    held = [bindings.stages.get(h.binding_id) for h in handles]
    stages = [None if s is None else (s, s.live_stage, s.evaluation_stage, s.source_revision) for s in held]
    datablocks = {d.session_uid for d in (*bpy.data.objects, *bpy.data.meshes, *bpy.data.collections)}
    return repr(stored), stages, datablocks


def _calls(scene: TransactionScene, handle: BindingHandle) -> list[Callable[[], object]]:
    """The calls CONS-04 lists, on handle."""
    synchronize, attach = (lambda: handle.synchronize(0)), (lambda: handle.attach(scene.caller))
    cache = lambda: handle.cache([5])  # noqa: E731
    return [synchronize, cache, attach, handle.release, handle.reload, handle.retry_cleanup]


CALLS = 2 * 6  # each of _calls on the running binding and on the other


def _check_reentrant_calls(
    bindings: Bindings, scene: TransactionScene, running: BindingHandle, other: BindingHandle
) -> int:
    """Make each call on both bindings; each raises, changing nothing. How many were made."""
    before = _held(bindings, (running, other))
    calls = [*_calls(scene, running), *_calls(scene, other)]
    for call in calls:
        with pytest.raises(ReentrantCallError):
            call()
    assert _held(bindings, (running, other)) == before
    return len(calls)


def test_calls_during_a_synchronization_raise(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CONS-01, CONS-04, API-05 on F-SOURCE-CHANGE "reentrant": from inside the evaluation step, each call on the
    # binding evaluating and on another raises and changes nothing; set_settings writes the configuration, the
    # running attempt records the settings it started with, and the synchronization then completes.
    with transaction.source_change(tmp_path) as scene:
        handle, other = _binding(bindings, scene, "Shot"), _binding(bindings, scene, "Other")
        chain = _core.SceneIndexChain
        made: list[int] = []

        def reentering(stage: Usd.Stage) -> _core.SceneIndexChain:
            made.append(_check_reentrant_calls(bindings, scene, handle, other))
            assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE).state is ResultState.SUCCESS
            return chain(stage)

        monkeypatch.setattr(_core, "SceneIndexChain", reentering)
        result = handle.synchronize(0)
        assert made == [CALLS]  # once
        assert result.state is ResultState.SUCCESS
        assert handle.requested_settings().payload_policy is PayloadPolicy.LOAD_NONE
        last = binding_state.read_last_attempt(destination(handle))
        assert (
            isinstance(last, id_property_records.LoadedRecord)
            and last.record.attempted_settings.payload_policy is PayloadPolicy.LOAD_ALL
        )
        monkeypatch.setattr(_core, "SceneIndexChain", chain)
        assert handle.synchronize(0).state is ResultState.SUCCESS  # nothing left running


def test_calls_during_a_cache_call_raise(bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # CONS-04 on F-SOURCE-CHANGE "reentrant": from inside a cache call's evaluation step, each call raises and changes
    # nothing, set_settings writes the configuration, and the cache call then caches.
    with transaction.source_change(tmp_path) as scene:
        handle, other = _binding(bindings, scene, "Shot"), _binding(bindings, scene, "Other")
        assert handle.synchronize(0).state is ResultState.SUCCESS
        chain = _core.SceneIndexChain
        made: list[int] = []

        def reentering(stage: Usd.Stage) -> _core.SceneIndexChain:
            made.append(_check_reentrant_calls(bindings, scene, handle, other))
            assert other.set_settings(payload_policy=PayloadPolicy.LOAD_NONE).state is ResultState.SUCCESS
            return chain(stage)

        monkeypatch.setattr(_core, "SceneIndexChain", reentering)
        result = handle.cache([10])
        assert made == [CALLS]  # once
        assert result.state is ResultState.SUCCESS
        generation = binding_state.read_generation(destination(handle))
        assert isinstance(generation, id_property_records.LoadedRecord) and generation.record.cached_time_codes == (
            10.0,
        )
        assert other.requested_settings().payload_policy is PayloadPolicy.LOAD_NONE


def test_calls_during_a_cleanup_retry_raise(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A retry removes datablocks and writes the ledger, so it runs alone too: from inside its removal, each call
    # raises and changes nothing, set_settings writes the configuration, and the retry then resolves everything.
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        handle, other = _binding(bindings, scene, "Shot"), _binding(bindings, scene, "Other")
        failing_preparation(handle, scene, 0)
        remove = datablock_removal._batch_remove  # noqa: SLF001 - the step's module function
        made: list[int] = []

        def reentering(datablocks: Sequence[bpy.types.ID]) -> None:
            if not made:  # the first level's call
                made.append(_check_reentrant_calls(bindings, scene, handle, other))
                assert other.set_settings(payload_policy=PayloadPolicy.LOAD_NONE).state is ResultState.SUCCESS
            remove(datablocks)

        monkeypatch.setattr(datablock_removal, "_batch_remove", reentering)
        result = handle.retry_cleanup()
        assert made == [CALLS]  # once
        assert (result.state, result.pending_cleanup_diagnostics) == (ResultState.SUCCESS, ())
        assert other.requested_settings().payload_policy is PayloadPolicy.LOAD_NONE
        assert handle.synchronize(0).state is ResultState.SUCCESS  # nothing left running


def test_an_exception_escaping_a_synchronization_ends_it(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only a bug escapes the transaction, and the next call still runs.
    with transaction.source_change(tmp_path) as scene:
        handle = _binding(bindings, scene, "Shot")

        def failing(*_args: object) -> None:
            raise RuntimeError("injected bug")

        monkeypatch.setattr(synchronization.transaction, "synchronize", failing)
        with pytest.raises(RuntimeError, match="injected bug"):
            handle.synchronize(0)
        assert handle.reload().state is ResultState.SUCCESS
