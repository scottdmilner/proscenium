"""When a binding's runtime stages are made, kept, and let go (source-access.md#source-stages; UNDO-06, SRC-02).

The registry is runtime state keyed by binding identity: proscenium.api.bindings says which
bindings exist and which can't be read; tests/blender/test_synchronization.py runs these rules
through undo, redo, and removed scenes.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from fixtures import source_access
from proscenium.core.binding_ids import BindingId
from proscenium.core.source_access import AttachedSource, FileSource, PayloadPolicy, StageRegistry

if TYPE_CHECKING:
    from pathlib import Path

F, M = BindingId("f"), BindingId("m")  # a file binding and an attached one


def test_a_bindings_stages_are_made_once_and_reused(tmp_path: Path) -> None:
    with source_access.reattach(tmp_path) as scene:
        registry = StageRegistry()
        assert registry.get(F) is None
        file_backed, attached = registry.file(F, scene.root), registry.attached(M, "shot")
        assert isinstance(file_backed.source, FileSource)
        assert isinstance(attached.source, AttachedSource)
        assert (registry.file(F, scene.root), registry.attached(M, "shot")) == (file_backed, attached)
        assert (registry.get(F), registry.get(M)) == (file_backed, attached)
        assert F in registry
        assert BindingId("other") not in registry


def test_stages_on_another_root_are_replaced(tmp_path: Path) -> None:
    # As when a "//" path resolves elsewhere once the .blend is saved elsewhere.
    with source_access.reattach(tmp_path) as scene:
        moved = tmp_path / "moved"
        shutil.copytree(scene.root.parent, moved)
        registry = StageRegistry()
        first = registry.file(F, scene.root)
        first.acquire(PayloadPolicy.LOAD_ALL)
        second = registry.file(F, moved / scene.root.name)
        assert second is not first
        assert second.evaluation_stage is None  # the new file opens at its first acquisition
        assert registry.get(F) is second


def test_an_attached_source_keeps_its_attachment(tmp_path: Path) -> None:
    with source_access.reattach(tmp_path) as scene:
        registry = StageRegistry()
        stages = registry.attached(M, "shot")
        stages.attach(scene.caller)
        assert registry.attached(M, "shot").live_stage == scene.caller


def _pruned(tmp_path: Path, synchronizable: dict[BindingId, bool]) -> dict[BindingId, tuple[bool, bool, bool]]:
    """For a file source F and an attached source M, both acquired: their state after prune.

    Whether each is still registered, still has its evaluation stage, and, for M, is still attached.
    """
    with source_access.reattach(tmp_path) as scene:
        registry = StageRegistry()
        registry.file(F, scene.root).acquire(PayloadPolicy.LOAD_ALL)
        attached = registry.attached(M, "shot")
        attached.attach(scene.caller)
        attached.acquire(PayloadPolicy.LOAD_ALL)
        registry.prune(synchronizable)
        found = {}
        for binding_id in (F, M):
            stages = registry.get(binding_id)
            found[binding_id] = (
                stages is not None,
                stages is not None and stages.evaluation_stage is not None,
                stages is not None and stages.live_stage is not None,
            )
        return found


def test_prune_keeps_the_stages_of_existing_bindings(tmp_path: Path) -> None:
    assert _pruned(tmp_path, {F: True, M: True}) == {F: (True, True, True), M: (True, True, True)}


def test_prune_drops_a_file_source_whose_binding_is_gone_or_unreadable(tmp_path: Path) -> None:
    assert _pruned(tmp_path, {M: True})[F] == (False, False, False)
    assert _pruned(tmp_path, {F: False, M: True})[F] == (False, False, False)


def test_prune_keeps_a_gone_attached_bindings_attachment(tmp_path: Path) -> None:
    # UNDO-06: undo removes no attachment, so redo finds the binding attached; its evaluation stage goes.
    assert _pruned(tmp_path, {F: True})[M] == (True, False, True)
    # One whose configuration can't be read keeps everything, as an existing binding does.
    assert _pruned(tmp_path, {F: True, M: False})[M] == (True, True, True)


def test_release_reaches_every_binding_with_the_key(tmp_path: Path) -> None:
    # SRC-02: stages whose binding is gone included, since they keep their attachment.
    with source_access.reattach(tmp_path) as scene:
        registry = StageRegistry()
        with_key = [registry.attached(binding_id, "shot") for binding_id in (BindingId("a"), BindingId("b"))]
        other = registry.attached(BindingId("c"), "other")
        for stages in (*with_key, other):
            stages.attach(scene.caller)
            stages.acquire(PayloadPolicy.LOAD_ALL)
        registry.prune({BindingId("b"): True, BindingId("c"): True})  # "a" is gone
        registry.release("shot")
        assert [(s.live_stage, s.evaluation_stage) for s in with_key] == [(None, None), (None, None)]
        assert other.live_stage == scene.caller
        assert other.evaluation_stage is not None
