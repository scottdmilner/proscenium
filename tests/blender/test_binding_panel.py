"""The temporary UI's binding panel: the scene's bindings, their states, and a synchronize button (M7 plan, F2).

The panel's draw function draws into a recording layout (support/recording_layout.py); its synchronize operator is
called as Blender calls it. Expected states come from what each test did to its bindings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import interaction
from proscenium.binding.results import ResultState
from proscenium.interface import binding_panel
from support import binding_copy_operations
from support.recording_layout import RecordingLayout

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.api.bindings import BindingHandle, Bindings
    from proscenium.binding.source_access import BindingId


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _drawn() -> RecordingLayout:
    layout = RecordingLayout()
    binding_panel.draw_bindings(layout, _scene())
    return layout


def test_a_scene_without_bindings_says_so(bindings: Bindings) -> None:
    del bindings
    assert _drawn().labels == [("No bindings", "NONE", True)]


def test_each_binding_shows_its_state_and_a_button(bindings: Bindings, tmp_path: Path) -> None:
    # Each binding: its name, attached or not, its state as it changes, and a synchronize button naming it.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle: BindingHandle = bindings.create_binding(_scene(), name="Shot")
        layout = _drawn()
        assert layout.labels == [("Shot", "UNLINKED", True), ("Not synchronized", "NONE", True)]
        [button] = layout.operators
        assert (button.idname, button.properties) == ("proscenium.synchronize", {"binding_id": handle.binding_id})
        assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        assert _drawn().labels == [("Shot", "LINKED", True), ("Up to date", "NONE", True)]
        handle.release()
        assert _drawn().labels == [("Shot", "UNLINKED", True), ("May be out of date", "NONE", True)]
        assert handle.synchronize(0.0).state is ResultState.FATAL_FAILURE
        assert _drawn().labels[1] == ("May be out of date; last attempt failed", "NONE", True)


def test_a_disabled_binding_shows_why_and_no_button(bindings: Bindings) -> None:
    # A binding whose destination was copied, with no index entry to choose between the copies, is disabled: the panel
    # says why, and offers no button.
    handle = bindings.create_binding(_scene(), name="Shot")
    copy = bpy.data.collections["Shot"].copy()
    _scene().collection.children.link(copy)

    def drop_entry(entries: dict[BindingId, bpy.types.Collection | None]) -> None:
        del entries[handle.binding_id]

    binding_copy_operations._write_entries(drop_entry)  # noqa: SLF001
    layout = _drawn()
    assert not layout.operators
    [(_, icon, _), (reason, error_icon, _)] = layout.labels
    assert icon == "UNLINKED" and error_icon == "ERROR" and reason.startswith("Copies with no canonical candidate")


def test_the_button_synchronizes_and_pushes_no_step_of_its_own(bindings: Bindings, tmp_path: Path) -> None:
    # The operator synchronizes at the scene's current frame, and declares no UNDO, since the API pushes the step; a
    # failure reports the first diagnostic as an error, which a script calling it sees raised.
    assert "UNDO" not in binding_panel.PROSCENIUM_OT_synchronize.bl_options
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        with pytest.raises(RuntimeError, match="No stage is attached"):  # a script sees the error report raised
            bpy.ops.proscenium.synchronize(binding_id=handle.binding_id)  # ty: ignore[unresolved-attribute]
        assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
        assert bpy.ops.proscenium.synchronize(binding_id=handle.binding_id)  # ty: ignore[unresolved-attribute] == {"FINISHED"}
        assert [s.published for s in bindings.binding_statuses(_scene())] == [True]
