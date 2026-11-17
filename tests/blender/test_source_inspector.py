"""The temporary UI's source inspector: a binding's live stage in the scene graph widget, synced with the selection.

On F-NESTED-SELECTION, whose crates are native instances, so a row inside one has the instance root as its floor.
The widget's own tests cover the tree; these cover what the inspector hosts and syncs. The view's callbacks and the
source selection's listener are called as the widget and the API call them; the panel's header and its line for the
selected prim draw into a recording layout (support/recording_layout.py). The property viewer
below the tree is read through its view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
from pxr import Sdf, Usd

from fixtures import interaction
from proscenium.api.bindings import PersistentSelection, SelectionEntry
from proscenium.binding.results import ResultState
from proscenium.interface import source_inspector
from proscenium_ui.property_viewer_widget import display as property_display
from proscenium_ui.property_viewer_widget.display import property_viewer_views
from proscenium_ui.scene_graph_widget import display
from proscenium_ui.scene_graph_widget.display import scene_graph_views
from support import undo
from support.recording_layout import RecordingLayout

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import pytest

    from proscenium.api.bindings import BindingHandle, Bindings

CRATE_A = "/World/CrateA"
INSIDE_CRATE_A = f"{CRATE_A}/Body"  # an instance proxy: its floor is CrateA
CRATE_B = "/World/Shelf/CrateB"


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _inspect(handle: BindingHandle) -> None:
    setattr(_scene(), source_inspector.BINDING_PROPERTY, handle.binding_id)  # its update shows the stage


def _sync(on: bool) -> None:
    setattr(_scene(), source_inspector.SYNCED_PROPERTY, on)


def _selection() -> PersistentSelection:
    from proscenium.api import bindings

    return bindings.BINDINGS.source_selection(_scene())


def _shown_prim() -> Sdf.Path | None:
    return property_viewer_views.property_viewer_view(source_inspector.PROPERTY_VIEW_NAME).property_list_view.prim_path


def _synchronized(bindings: Bindings, tmp_path: Path) -> Iterator[tuple[BindingHandle, interaction.InteractionScene]]:
    with interaction.nested_selection(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        yield handle, scene


def test_the_inspector_shows_the_chosen_bindings_live_stage(bindings: Bindings, tmp_path: Path) -> None:
    # Without bindings, the header says there is none to inspect. With one, the dropdown chooses it by default; chosen,
    # its live stage shows in the view, which holds none of it, and the header draws the dropdown and the toggle and
    # asks for the tree. Released, the binding has no stage to show, which the header says.
    layout = RecordingLayout()
    assert not source_inspector.draw_inspector_header(layout, _scene())
    assert layout.labels[-1][0] == "No binding to inspect"
    for handle, _ in _synchronized(bindings, tmp_path):
        assert source_inspector.inspected_handle(_scene()) == handle
        _inspect(handle)
        assert scene_graph_views.scene_graph_view(source_inspector.VIEW_NAME).prim_tree_view.live_tree() is not None
        layout = RecordingLayout()
        assert source_inspector.draw_inspector_header(layout, _scene())
        assert layout.props == [source_inspector.BINDING_PROPERTY, source_inspector.SYNCED_PROPERTY]
        handle.release()
        layout = RecordingLayout()
        assert not source_inspector.draw_inspector_header(layout, _scene())
        assert layout.labels[-1][0] == "No stage attached"


def test_a_row_selects_its_floor_while_synced(bindings: Bindings, tmp_path: Path) -> None:
    # Synced, selecting a row inside an instance makes its instance root, its floor, the source selection and its
    # active entry; not synced, a row changes nothing.
    for handle, _ in _synchronized(bindings, tmp_path):
        _inspect(handle)
        source_inspector.tree_selection_changed(Sdf.Path(INSIDE_CRATE_A))
        assert _selection() == PersistentSelection((), None)
        _sync(True)
        source_inspector.tree_selection_changed(Sdf.Path(INSIDE_CRATE_A))
        entry = SelectionEntry(handle.binding_id, CRATE_A)
        assert _selection() == PersistentSelection((entry,), entry)


def test_the_source_selection_selects_its_active_row_while_synced(bindings: Bindings, tmp_path: Path) -> None:
    # As the source selection's listener, synced, the inspector selects the active entry's row; not synced, it leaves
    # the tree as it was; and turning syncing on selects the active entry's row at once.
    for handle, _ in _synchronized(bindings, tmp_path):
        _inspect(handle)
        bindings.add_selection_listener(source_inspector.source_selection_changed)
        shelf = SelectionEntry(handle.binding_id, "/World/Shelf")
        bindings.set_source_selection(_scene(), PersistentSelection((shelf,), shelf))
        assert display.selected_path(source_inspector.VIEW_NAME) is None
        _sync(True)
        assert display.selected_path(source_inspector.VIEW_NAME) == Sdf.Path("/World/Shelf")
        crate = SelectionEntry(handle.binding_id, CRATE_A)
        bindings.set_source_selection(_scene(), PersistentSelection((shelf, crate), crate))
        assert display.selected_path(source_inspector.VIEW_NAME) == Sdf.Path(CRATE_A)
        bindings.set_source_selection(_scene(), PersistentSelection((), None))
        assert display.selected_path(source_inspector.VIEW_NAME) is None


def test_the_selected_prim_says_whether_it_is_displayed(bindings: Bindings, tmp_path: Path) -> None:
    # Below the tree, the selected prim is marked displayed when the generation shown displays it, and not otherwise,
    # as for the abstract prototype.
    for handle, _ in _synchronized(bindings, tmp_path):
        _inspect(handle)
        for path, text in ((CRATE_A, "Displayed"), ("/Prototypes/Crate", "Not displayed")):
            display.select_prim(source_inspector.VIEW_NAME, Sdf.Path(path))
            layout = RecordingLayout()
            source_inspector.draw_selected_prim(layout, _scene())
            assert [label for label, _, _ in layout.labels] == [text], path


def test_the_view_shows_only_where_its_tab_is() -> None:
    class _Region:
        def __init__(self, kind: str, category: str) -> None:
            self.type, self.active_panel_category = kind, category

    class _Area:
        type = "VIEW_3D"

    assert source_inspector.shows_in_region(_Area(), _Region("UI", "Proscenium"))
    assert not source_inspector.shows_in_region(_Area(), _Region("UI", "Tool"))
    assert not source_inspector.shows_in_region(_Area(), _Region("WINDOW", "Proscenium"))


def test_a_new_live_stage_is_shown_after_the_draw_that_finds_it(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Attached to another stage, the binding's live stage differs from the one shown, which a draw finds and, since a
    # draw may write no data, schedules showing; once that runs, the view shows the new stage and no draw schedules it
    # again.
    scheduled = []
    monkeypatch.setattr(source_inspector.widget_updates, "schedule", lambda timer, _delay: scheduled.append(timer))
    for handle, scene in _synchronized(bindings, tmp_path):
        _inspect(handle)
        assert source_inspector.draw_inspector_header(RecordingLayout(), _scene())
        assert not scheduled
        other = Usd.Stage.Open(str(scene.root_layer_path))
        assert handle.attach(other).state is not ResultState.FATAL_FAILURE
        assert source_inspector.draw_inspector_header(RecordingLayout(), _scene())
        [show] = scheduled
        show()
        tree = scene_graph_views.scene_graph_view(source_inspector.VIEW_NAME).prim_tree_view.live_tree()
        assert tree is not None
        assert source_inspector.draw_inspector_header(RecordingLayout(), _scene())
        assert len(scheduled) == 1


def test_a_synced_row_selection_is_an_undo_step(bindings: Bindings, tmp_path: Path) -> None:
    # Synced, a row that changes the source selection pushes an undo step, which an undo removes; undo doesn't restore
    # the tree, which the window manager holds, so the tree takes up the restored selection, and again after a redo.
    # A row whose floor is already the selection pushes none, so the next undo goes back past CrateA's selection.
    undo.require_global_undo()
    for handle, _ in _synchronized(bindings, tmp_path):
        _inspect(handle)
        _sync(True)
        undo.push("before the row's selection")
        display.select_prim(source_inspector.VIEW_NAME, Sdf.Path(CRATE_A))
        source_inspector.tree_selection_changed(Sdf.Path(CRATE_A))
        crate = SelectionEntry(handle.binding_id, CRATE_A)
        assert _selection() == PersistentSelection((crate,), crate)
        display.select_prim(source_inspector.VIEW_NAME, Sdf.Path(INSIDE_CRATE_A))
        source_inspector.tree_selection_changed(Sdf.Path(INSIDE_CRATE_A))  # CrateA again: no step
        undo.undo()
        assert _selection() == PersistentSelection((), None)
        assert display.selected_path(source_inspector.VIEW_NAME) is None
        undo.redo()
        assert _selection() == PersistentSelection((crate,), crate)
        assert display.selected_path(source_inspector.VIEW_NAME) == Sdf.Path(CRATE_A)


def test_the_property_viewer_shows_the_selected_prims_properties(bindings: Bindings, tmp_path: Path) -> None:
    # Below the tree, the property viewer shows the prim a row selects, synced or not, and the one the source selection
    # selects while synced, or none when it selects none.
    for handle, _ in _synchronized(bindings, tmp_path):
        _inspect(handle)
        bindings.add_selection_listener(source_inspector.source_selection_changed)
        assert _shown_prim() is None
        source_inspector.tree_selection_changed(Sdf.Path(INSIDE_CRATE_A))
        assert _shown_prim() == Sdf.Path(INSIDE_CRATE_A)
        _sync(True)
        shelf = SelectionEntry(handle.binding_id, "/World/Shelf")
        bindings.set_source_selection(_scene(), PersistentSelection((shelf,), shelf))
        assert _shown_prim() == Sdf.Path("/World/Shelf")
        bindings.set_source_selection(_scene(), PersistentSelection((), None))
        assert _shown_prim() is None


def test_a_jump_selects_the_targets_prim_and_property(bindings: Bindings, tmp_path: Path) -> None:
    # A target's jump button selects its prim in the tree as a row click would, so synced it becomes the source
    # selection, and its property in the property viewer.
    for handle, _ in _synchronized(bindings, tmp_path):
        _inspect(handle)
        _sync(True)
        source_inspector.jump_to_target(Sdf.Path(f"{CRATE_B}.xformOp:translate"))
        assert display.selected_path(source_inspector.VIEW_NAME) == Sdf.Path(CRATE_B)
        assert _shown_prim() == Sdf.Path(CRATE_B)
        assert property_display.selected_path(source_inspector.PROPERTY_VIEW_NAME) == Sdf.Path(
            f"{CRATE_B}.xformOp:translate"
        )
        crate = SelectionEntry(handle.binding_id, CRATE_B)
        assert _selection() == PersistentSelection((crate,), crate)


def test_the_property_viewer_shows_values_at_the_shown_time_code(bindings: Bindings, tmp_path: Path) -> None:
    # The values are the ones at the time code the display shows, here the one it was synchronized at, which a draw
    # gives the view.
    for handle, _ in _synchronized(bindings, tmp_path):
        _inspect(handle)
        view = property_viewer_views.property_viewer_view(source_inspector.PROPERTY_VIEW_NAME)
        assert view.property_list_view.time_code == Usd.TimeCode.Default()
        assert source_inspector.draw_inspector_header(RecordingLayout(), _scene())
        assert view.property_list_view.time_code == Usd.TimeCode(0.0)
