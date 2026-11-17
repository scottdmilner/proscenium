"""Interaction after a reopening: correspondence loaded from Blender data, and a source unavailable (lifecycle.md).

DECISIONS.md "Persisted correspondence": after reopening, once the binding's stage is attached again, the core builds
correspondence from the saved manifest and objects without synchronizing (ICON-35). Without a live stage, the saved
display stays as it was, each interaction function reports the source unavailable, and the persistent selection is kept
(INSP-10, ICON-08, ICON-09). Answers are compared by manifest entry key (support/interaction_answers.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import interaction, source_access
from proscenium_sync import synchronization
from proscenium_sync.api.bindings import BindingHandle, PersistentSelection, SelectionEntry, SourceUnavailableError
from proscenium_sync.binding_persistence import binding_state, id_property_records
from proscenium_sync.results import ResultState
from support.blend import collection_content, save_and_reopen
from support.interaction_answers import answers, object_entry_keys
from support.offline_display import expected_content, publish_by_hand
from support.usd import open_stage_without_cache

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from proscenium_sync.api.bindings import Bindings


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _records() -> tuple[object, object]:
    destination = bpy.data.collections["Shot"]
    return (
        id_property_records.stored(destination, binding_state.GENERATION_KEY),
        id_property_records.stored(destination, binding_state.ATTEMPT_KEY),
    )


def _forbid_synchronizing(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("synchronized or cached")

    monkeypatch.setattr(synchronization, "synchronize", forbidden)
    monkeypatch.setattr(synchronization, "cache", forbidden)


def test_correspondence_loads_after_reopening(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ICON-35 on F-KIND-HIERARCHY: saved and reopened, with the caller's stage attached again and nothing
    # synchronized or cached, resolve_pick, displayed, highlight_targets, and select_targets answer as before saving,
    # and the generation record and last attempt are as saved.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        before = answers(handle, scene.stage)
        records = _records()
        save_and_reopen(tmp_path / "reopened.blend")
        with monkeypatch.context() as patched:
            _forbid_synchronizing(patched)
            restored = BindingHandle(handle.binding_id)
            stage = open_stage_without_cache(scene.root_layer_path)
            assert restored.attach(stage).state is not ResultState.FATAL_FAILURE
            assert answers(restored, stage) == before
            assert _records() == records


def test_without_its_source_a_reopened_display_has_no_interaction(bindings: Bindings, tmp_path: Path) -> None:
    # F-OFFLINE "no-interaction" (INSP-10, ICON-08, ICON-09): reopened with its source files moved away, the saved
    # display is unchanged, each interaction function reports the source unavailable, and the persistent selection is
    # unchanged after each; once the caller's stage, which kept its layers open, is attached again, they answer as
    # before saving.
    with source_access.offline(tmp_path) as scene:
        caller = scene.open_caller()
        handle = bindings.create_binding(_scene(), name="Shot")
        assert handle.attach(caller).state is not ResultState.FATAL_FAILURE
        publish_by_hand(handle.binding_id, bpy.data.collections["Shot"], scene.display)
        selection = PersistentSelection((SelectionEntry(handle.binding_id, "/World/Ref"),), None)
        bindings.set_source_selection(_scene(), selection)
        before = answers(handle, caller)
        scene.move_away()
        save_and_reopen(tmp_path / "offline.blend")
        assert collection_content(bpy.data.collections["Shot"]) == expected_content(scene.display)
        restored = BindingHandle(handle.binding_id)
        obj = next(iter(object_entry_keys(restored.binding_id)))
        view_layer = _scene().view_layers[0]
        calls: list[Callable[[], object]] = [
            lambda: restored.resolve_pick(obj, obj.matrix_world),
            lambda: restored.select_targets(["/World/Ref"], None),
            lambda: restored.displayed(["/World"]),
            lambda: restored.highlight_targets(["/World"]),
            lambda: restored.selection_from_blender(None, view_layer),
        ]
        for call in calls:
            with pytest.raises(SourceUnavailableError):
                call()
            assert bindings.source_selection(_scene()) == selection
        assert bindings.resolve_source_selection(_scene()).unresolved == selection.entries
        assert restored.attach(caller).state is not ResultState.FATAL_FAILURE
        assert answers(restored, caller) == before
        assert bindings.resolve_source_selection(_scene()).resolved == selection.entries
