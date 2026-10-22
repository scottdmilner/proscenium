"""When a binding's runtime stages are made, kept, and let go (source-access.md#source-stages; UNDO-06, SRC-02).

The registry is runtime state keyed by binding identity: proscenium.api.bindings says which
bindings exist and which can't be read; tests/blender/test_synchronization.py runs these rules
through undo, redo, and removed scenes.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from fixtures import source_access
from proscenium.core.source_access import AttachedSource, FileSource, PayloadPolicy, StageRegistry

if TYPE_CHECKING:
    from pathlib import Path


def test_a_bindings_stages_are_made_once_and_reused(tmp_path: Path) -> None:
    with source_access.reattach(tmp_path) as scene:
        registry = StageRegistry()
        assert registry.get("f") is None
        file_backed, attached = registry.file("f", scene.root), registry.attached("m", "shot")
        assert isinstance(file_backed.source, FileSource)
        assert isinstance(attached.source, AttachedSource)
        assert (registry.file("f", scene.root), registry.attached("m", "shot")) == (file_backed, attached)
        assert (registry.get("f"), registry.get("m")) == (file_backed, attached)
        assert "f" in registry
        assert "other" not in registry


def test_stages_on_another_root_are_replaced(tmp_path: Path) -> None:
    # As when a "//" path resolves elsewhere once the .blend is saved elsewhere.
    with source_access.reattach(tmp_path) as scene:
        moved = tmp_path / "moved"
        shutil.copytree(scene.root.parent, moved)
        registry = StageRegistry()
        first = registry.file("f", scene.root)
        first.acquire(PayloadPolicy.LOAD_ALL)
        second = registry.file("f", moved / scene.root.name)
        assert second is not first
        assert second.evaluation_stage is None  # the new file opens at its first acquisition
        assert registry.get("f") is second


def test_an_attached_source_keeps_its_attachment(tmp_path: Path) -> None:
    with source_access.reattach(tmp_path) as scene:
        registry = StageRegistry()
        stages = registry.attached("m", "shot")
        stages.attach(scene.caller)
        assert registry.attached("m", "shot").live_stage == scene.caller


def _pruned(tmp_path: Path, existing: set[str], unreadable: set[str]) -> dict[str, tuple[bool, bool, bool]]:
    """For a file source "f" and an attached source "m", both acquired: their state after prune.

    Whether each is still registered, still has its evaluation stage, and, for "m", is still attached.
    """
    with source_access.reattach(tmp_path) as scene:
        registry = StageRegistry()
        registry.file("f", scene.root).acquire(PayloadPolicy.LOAD_ALL)
        attached = registry.attached("m", "shot")
        attached.attach(scene.caller)
        attached.acquire(PayloadPolicy.LOAD_ALL)
        registry.prune(existing, unreadable)
        found = {}
        for binding_id in ("f", "m"):
            stages = registry.get(binding_id)
            found[binding_id] = (
                stages is not None,
                stages is not None and stages.evaluation_stage is not None,
                stages is not None and stages.live_stage is not None,
            )
        return found


def test_prune_keeps_the_stages_of_existing_bindings(tmp_path: Path) -> None:
    assert _pruned(tmp_path, {"f", "m"}, set()) == {"f": (True, True, True), "m": (True, True, True)}


def test_prune_drops_a_file_source_whose_binding_is_gone_or_unreadable(tmp_path: Path) -> None:
    assert _pruned(tmp_path, {"m"}, set())["f"] == (False, False, False)
    assert _pruned(tmp_path, {"f", "m"}, {"f"})["f"] == (False, False, False)


def test_prune_keeps_a_gone_attached_bindings_attachment(tmp_path: Path) -> None:
    # UNDO-06: undo removes no attachment, so redo finds the binding attached; its evaluation stage goes.
    assert _pruned(tmp_path, {"f"}, set())["m"] == (True, False, True)
    # One whose configuration can't be read keeps everything, as an existing binding does.
    assert _pruned(tmp_path, {"f", "m"}, {"m"})["m"] == (True, True, True)


def test_release_reaches_every_binding_with_the_key(tmp_path: Path) -> None:
    # SRC-02: stages whose binding is gone included, since they keep their attachment.
    with source_access.reattach(tmp_path) as scene:
        registry = StageRegistry()
        with_key = [registry.attached(binding_id, "shot") for binding_id in ("a", "b")]
        other = registry.attached("c", "other")
        for stages in (*with_key, other):
            stages.attach(scene.caller)
            stages.acquire(PayloadPolicy.LOAD_ALL)
        registry.prune({"b", "c"}, set())  # "a" is gone
        registry.release("shot")
        assert [(s.live_stage, s.evaluation_stage) for s in with_key] == [(None, None), (None, None)]
        assert other.live_stage == scene.caller
        assert other.evaluation_stage is not None
