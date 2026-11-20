"""The temporary UI's binding panel: the scene's bindings, their states, and their buttons (M7 plan, F2).

The panel's draw function draws into a recording layout (support/recording_layout.py); its operators are called as
Blender calls them. Expected states come from what each test did to its bindings.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import bpy
import pytest

from fixtures import interaction
from proscenium.interface import binding_panel
from proscenium_sync.persistence import binding_state
from proscenium_sync.results import ResultState
from proscenium_sync.runtime import binding_operations
from support import binding_copy_operations
from support.recording_layout import DrawnOperator, RecordingLayout

from .removal_failures import fail_removing

if TYPE_CHECKING:
    from proscenium_sync.bindings import BindingHandle, Bindings
    from proscenium_sync.source_access import BindingId


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _drawn() -> RecordingLayout:
    layout = RecordingLayout()
    binding_panel.draw_bindings(layout, _scene())
    return layout


def _synchronize_buttons(layout: RecordingLayout) -> list[DrawnOperator]:
    return [drawn for drawn in layout.operators if drawn.idname == "proscenium.synchronize"]


def _remove_buttons(layout: RecordingLayout) -> list[DrawnOperator]:
    return [drawn for drawn in layout.operators if drawn.idname == "proscenium.remove_binding"]


def _disable(handle: BindingHandle, destination: str) -> None:
    """Copy the binding's destination, and drop its index entry, so no copy is canonical and the binding is disabled."""
    copy = bpy.data.collections[destination].copy()
    _scene().collection.children.link(copy)

    def drop_entry(entries: dict[BindingId, bpy.types.Collection | None]) -> None:
        del entries[handle.binding_id]

    binding_copy_operations._write_entries(drop_entry)  # noqa: SLF001


def test_a_scene_without_bindings_says_so_under_the_add_button(bindings: Bindings) -> None:
    del bindings
    layout = _drawn()
    assert layout.labels == [("No bindings", "NONE", True)]
    assert [(drawn.idname, drawn.icon) for drawn in layout.operators] == [("proscenium.add_binding", "ADD")]


def test_each_binding_shows_its_state_and_a_button(bindings: Bindings, tmp_path: Path) -> None:
    # Each binding: its name, attached or not, its state as it changes, and a synchronize button naming it.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle: BindingHandle = bindings.create_binding(_scene(), name="Shot")
        layout = _drawn()
        assert layout.labels == [("Shot", "UNLINKED", True), ("Not synchronized", "NONE", True)]
        [button] = _synchronize_buttons(layout)
        assert (button.idname, button.properties) == ("proscenium.synchronize", {"binding_id": handle.binding_id})
        [remove] = _remove_buttons(layout)
        assert (remove.icon, remove.properties) == ("X", {"binding_id": handle.binding_id})
        assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        assert _drawn().labels == [("Shot", "LINKED", True), ("Up to date", "NONE", True)]
        handle.release()
        assert _drawn().labels == [("Shot", "UNLINKED", True), ("May be out of date", "NONE", True)]
        assert handle.synchronize(0.0).state is ResultState.FATAL_FAILURE
        assert _drawn().labels[1] == ("May be out of date; last attempt failed", "NONE", True)


def test_statuses_resolve_each_binding_and_generation_once(bindings: Bindings, tmp_path: Path) -> None:
    with interaction.kind_hierarchy(tmp_path) as scene:
        handles = [bindings.create_binding(_scene(), name=name) for name in ("A", "B")]
        for handle in handles:
            handle.attach(scene.stage)
            assert handle.synchronize(0).is_success
        with (
            patch.object(binding_operations, "find_binding", wraps=binding_operations.find_binding) as individual,
            patch.object(binding_state, "read_generation", wraps=binding_state.read_generation) as generations,
            patch.object(bindings.stages, "get", wraps=bindings.stages.get) as stages,
        ):
            statuses = bindings.binding_statuses(_scene())
        assert (individual.call_count, generations.call_count, stages.call_count) == (0, 2, 2)
        assert [(s.binding_id, s.attached, s.possibly_out_of_date, s.published) for s in statuses] == [
            (handle.binding_id, True, False, True) for handle in handles
        ]


def test_a_disabled_binding_shows_why_and_no_button(bindings: Bindings) -> None:
    # A binding whose destination was copied, with no index entry to choose between the copies, is disabled: the panel
    # says why, and offers no button, since both operations would refuse it.
    _disable(bindings.create_binding(_scene(), name="Shot"), "Shot")
    layout = _drawn()
    assert not _synchronize_buttons(layout)
    assert not _remove_buttons(layout)
    [(_, icon, _), (reason, error_icon, _)] = layout.labels
    assert icon == "UNLINKED" and error_icon == "ERROR" and reason.startswith("Copies with no canonical candidate")


def test_a_binding_with_copies_has_no_remove_button(bindings: Bindings) -> None:
    # A copy of the destination, with the index's entry keeping the original canonical: the binding still synchronizes,
    # but removal refuses it while the copy's records remain, so the panel says so and offers no remove button.
    handle = bindings.create_binding(_scene(), name="Shot")
    _scene().collection.children.link(bpy.data.collections["Shot"].copy())
    layout = _drawn()
    [button] = _synchronize_buttons(layout)
    assert button.properties == {"binding_id": handle.binding_id}
    assert not _remove_buttons(layout)
    assert layout.labels == [
        ("Shot", "UNLINKED", True),
        ("Not synchronized", "NONE", True),
        ("Has copies, so it can't be removed", "INFO", True),
    ]


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


def test_the_add_button_creates_a_binding_with_the_file_attached(bindings: Bindings, tmp_path: Path) -> None:
    # The binding takes the file's name, is attached to a stage of that file, and is undoable as a step of its own.
    assert "UNDO" in binding_panel.PROSCENIUM_OT_add_binding.bl_options
    with interaction.kind_hierarchy(tmp_path) as scene:
        path = scene.root_layer_path
        assert bpy.ops.proscenium.add_binding(filepath=str(path)) == {"FINISHED"}  # ty: ignore[unresolved-attribute]
        [status] = bindings.binding_statuses(_scene())
        assert (status.name, status.attached, status.published) == (path.stem, True, False)
        stage = bindings.live_stage(status.binding_id)
        assert stage is not None and Path(stage.GetRootLayer().realPath) == path
        assert bpy.ops.proscenium.synchronize(binding_id=status.binding_id) == {"FINISHED"}  # ty: ignore[unresolved-attribute]


def test_the_add_button_leaves_no_binding_for_a_file_that_doesnt_open(bindings: Bindings, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Can't open"):  # a script sees the error report raised
        bpy.ops.proscenium.add_binding(filepath=str(tmp_path / "missing.usda"))  # ty: ignore[unresolved-attribute]
    assert bindings.binding_statuses(_scene()) == []


def test_the_remove_button_removes_the_binding_and_declares_no_undo(bindings: Bindings, tmp_path: Path) -> None:
    # The operator removes the binding, its content and its destination, and declares no UNDO, since the API pushes the
    # step (test_binding_removal checks it); the panel then lists no bindings.
    assert "UNDO" not in binding_panel.PROSCENIUM_OT_remove_binding.bl_options
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
        assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        assert bpy.ops.proscenium.remove_binding(binding_id=handle.binding_id) == {"FINISHED"}  # ty: ignore[unresolved-attribute]
        assert bindings.binding_statuses(_scene()) == []
        assert "Shot" not in bpy.data.collections
        assert _drawn().labels == [("No bindings", "NONE", True)]


def test_the_remove_operator_reports_why_a_disabled_binding_refuses(bindings: Bindings) -> None:
    # The panel offers no remove button for a binding that isn't usable, but a script can call the operator: it refuses,
    # changing nothing, and the script sees the error report, which says why, raised.
    handle = bindings.create_binding(_scene(), name="Shot")
    _disable(handle, "Shot")
    with pytest.raises(RuntimeError, match="no canonical candidate"):
        bpy.ops.proscenium.remove_binding(binding_id=handle.binding_id)  # ty: ignore[unresolved-attribute]
    assert [s.binding_id for s in bindings.binding_statuses(_scene())] == [handle.binding_id]


def test_the_remove_button_warns_of_disposals_left_pending(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    # A removal that leaves disposals pending in the ledger completes with issues: the binding is gone, and the warning
    # report, which background mode prints, counts the issues and gives the first one. Each object fails to be removed,
    # and so does its bounds mesh, which it uses: two issues for each object.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
        assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        objects = set(bpy.data.collections["Shot"].objects)
        fail_removing(monkeypatch, objects)
        capfd.readouterr()
        assert bpy.ops.proscenium.remove_binding(binding_id=handle.binding_id) == {"FINISHED"}  # ty: ignore[unresolved-attribute]
        assert bindings.binding_statuses(_scene()) == []
        issues = 2 * len(objects)
        assert f"Warning: Removed, with {issues} issue(s): Couldn't remove managed" in capfd.readouterr().out
