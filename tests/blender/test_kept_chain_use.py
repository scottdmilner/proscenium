"""Synchronizations and cache calls capture from the binding's kept chain (M7 plan, C1).

On F-SOURCE-CHANGE (fixtures/transaction.py). A binding's synchronizations and cache calls share one chain over its
evaluation stage, which releasing the binding releases; a capture that fails or is discarded releases it, and the next
synchronization builds another. tests/bpy_free/test_kept_chain_lifetime.py checks what else releases it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from fixtures import transaction
from proscenium import core
from proscenium.binding.results import DiagnosticCode, ResultState

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from pxr import Usd

    from fixtures.transaction import TransactionScene
    from proscenium.api.bindings import BindingHandle, Bindings


def _binding(bindings: Bindings, scene: TransactionScene) -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
    assert handle.attach(scene.caller).state is ResultState.SUCCESS
    return handle


def _kept(bindings: Bindings, handle: BindingHandle) -> core.SceneIndexChain:
    stages = bindings.stages.get(handle.binding_id)
    assert stages is not None
    chain = stages.kept_chain
    assert isinstance(chain, core.SceneIndexChain)
    assert not chain.released
    return chain


def test_synchronizations_and_cache_calls_share_the_kept_chain(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with transaction.source_change(tmp_path) as scene:
        handle = _binding(bindings, scene)
        assert handle.synchronize(0).state is ResultState.SUCCESS
        chain = _kept(bindings, handle)
        capture = core.SceneIndexChain.capture
        captured_from: list[core.SceneIndexChain] = []

        def recording(chain: core.SceneIndexChain, time_code: Usd.TimeCode) -> core.Snapshot:
            captured_from.append(chain)
            return capture(chain, time_code)

        with monkeypatch.context() as patch:  # not monkeypatch.undo(), which would undo the bindings fixture's too
            patch.setattr(core.SceneIndexChain, "capture", recording)
            scene.edit()
            assert handle.synchronize(0).state is ResultState.SUCCESS
            assert handle.cache([5, 10]).state is ResultState.SUCCESS  # Mover varies, so each is captured
        assert captured_from == [chain] * 3
        assert _kept(bindings, handle) is chain
        handle.release()
        assert chain.released


def test_a_failed_capture_releases_the_kept_chain(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with transaction.source_change(tmp_path) as scene:
        handle = _binding(bindings, scene)
        assert handle.synchronize(0).state is ResultState.SUCCESS
        chain = _kept(bindings, handle)

        def failing(_chain: core.SceneIndexChain, _time_code: Usd.TimeCode) -> None:
            raise RuntimeError("injected failure")

        with monkeypatch.context() as patch:  # not monkeypatch.undo(), which would undo the bindings fixture's too
            patch.setattr(core.SceneIndexChain, "capture", failing)
            [diagnostic] = handle.synchronize(0).diagnostics
        assert diagnostic.code is DiagnosticCode.EVALUATION_FAILED
        assert chain.released
        assert handle.synchronize(0).state is ResultState.SUCCESS
        assert _kept(bindings, handle) is not chain


def test_a_discarded_capture_releases_the_kept_chain(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CONS-03: a layer changing during the capture discards it, and the chain that applied the change midway with it.
    with transaction.source_change(tmp_path) as scene:
        handle = _binding(bindings, scene)
        assert handle.synchronize(0).state is ResultState.SUCCESS
        chain = _kept(bindings, handle)
        capture = core.SceneIndexChain.capture

        def editing(chain: core.SceneIndexChain, time_code: Usd.TimeCode) -> core.Snapshot:
            scene.edit()
            return capture(chain, time_code)

        with monkeypatch.context() as patch:
            patch.setattr(core.SceneIndexChain, "capture", editing)
            [diagnostic] = handle.synchronize(0).diagnostics
        assert diagnostic.code is DiagnosticCode.SOURCE_CHANGED
        assert chain.released
        assert handle.synchronize(0).state is ResultState.SUCCESS
        assert _kept(bindings, handle) is not chain
