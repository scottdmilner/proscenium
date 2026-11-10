"""When a binding's runtime stages are made, kept, and let go (source-access.md#source-stages; UNDO-06, SRC-02).

The registry is runtime state keyed by binding identity: proscenium.api.bindings says which
bindings exist and which can't be read; tests/blender/test_synchronization.py runs these rules
through undo, redo, and removed scenes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fixtures import source_access
from proscenium.binding.source_access.identifiers import BindingId
from proscenium.binding.source_access.registry import StageRegistry
from proscenium.binding.source_access.stages import PayloadPolicy

if TYPE_CHECKING:
    from pathlib import Path

FIRST, SECOND = BindingId("first"), BindingId("second")


def test_a_bindings_stages_are_made_once_and_reused() -> None:
    registry = StageRegistry()
    assert registry.get(FIRST) is None
    first, second = (registry.get_or_create_binding_stages(binding_id) for binding_id in (FIRST, SECOND))
    assert first is not second
    assert (registry.get_or_create_binding_stages(FIRST), registry.get_or_create_binding_stages(SECOND)) == (
        first,
        second,
    )
    assert (registry.get(FIRST), registry.get(SECOND)) == (first, second)
    assert FIRST in registry
    assert BindingId("other") not in registry


def test_attaching_another_root_keeps_the_binding_and_drops_its_evaluation(tmp_path: Path) -> None:
    with source_access.reattach(tmp_path) as scene:
        registry = StageRegistry()
        stages = registry.get_or_create_binding_stages(FIRST)
        stages.attach(scene.caller)
        first = stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        stages.attach(scene.other_root)
        assert registry.get(FIRST) is stages
        assert stages.evaluation_stage is None
        assert stages.live_stage == scene.other_root
        second = stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        assert second != first
        assert second.GetRootLayer() == scene.other_root.GetRootLayer()


def test_an_attached_source_keeps_its_attachment(tmp_path: Path) -> None:
    with source_access.reattach(tmp_path) as scene:
        registry = StageRegistry()
        stages = registry.get_or_create_binding_stages(FIRST)
        stages.attach(scene.caller)
        assert registry.get_or_create_binding_stages(FIRST).live_stage == scene.caller


def _pruned(tmp_path: Path, existing: set[BindingId]) -> dict[BindingId, tuple[bool, bool, bool]]:
    """Whether each binding remains registered, has an evaluation stage, and stays attached after pruning."""
    with source_access.reattach(tmp_path) as scene:
        registry = StageRegistry()
        for binding_id in (FIRST, SECOND):
            stages = registry.get_or_create_binding_stages(binding_id)
            stages.attach(scene.caller)
            stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        registry.prune(existing)
        found = {}
        for binding_id in (FIRST, SECOND):
            stages = registry.get(binding_id)
            found[binding_id] = (
                stages is not None,
                stages is not None and stages.evaluation_stage is not None,
                stages is not None and stages.live_stage is not None,
            )
        return found


def test_prune_keeps_the_stages_of_existing_bindings(tmp_path: Path) -> None:
    assert _pruned(tmp_path, {FIRST, SECOND}) == {FIRST: (True, True, True), SECOND: (True, True, True)}


def test_prune_keeps_a_gone_attached_bindings_attachment(tmp_path: Path) -> None:
    # UNDO-06: undo removes no attachment, so redo finds the binding attached; its evaluation stage goes.
    assert _pruned(tmp_path, {FIRST})[SECOND] == (True, False, True)


def test_release_reaches_only_the_addressed_binding_even_after_pruning(tmp_path: Path) -> None:
    with source_access.reattach(tmp_path) as scene:
        registry = StageRegistry()
        first, second = (registry.get_or_create_binding_stages(binding_id) for binding_id in (FIRST, SECOND))
        for stages in (first, second):
            stages.attach(scene.caller)
            stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        registry.prune({SECOND})
        registry.release(FIRST)
        registry.release(FIRST)
        registry.release(BindingId("unknown"))
        assert (first.live_stage, first.evaluation_stage) == (None, None)
        assert second.live_stage == scene.caller
        assert second.evaluation_stage is not None
