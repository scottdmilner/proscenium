"""The display component's apply_selection and read_blender_selection on a binding's display (interaction-contract.md).

On F-KIND-HIERARCHY's display, through the core's correspondence over its display elements. Expected values come from
the fixture: Chair's component holds Seat, Back, and Legs, and Top is Table's. support/interaction_checks.py checks the
same functions through api/.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import interaction
from proscenium.binding.results import ResultState
from proscenium.interaction import blender_selection, display_correspondence

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from proscenium import core
    from proscenium.api.bindings import Bindings

CHAIR = "/World/Props/Chair"
SEAT, BACK, LEGS = f"{CHAIR}/Geom/Seat", f"{CHAIR}/Geom/Back", f"{CHAIR}/Legs"
TOP = "/World/Table/Top"


class _Display:
    """A synchronized F-KIND-HIERARCHY display: its elements, correspondence, and the active view layer."""

    elements: display_correspondence.DisplayElements
    correspondence: core.Correspondence
    view_layer: bpy.types.ViewLayer

    def __init__(self, bindings: Bindings, scene: interaction.InteractionScene) -> None:
        handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
        assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        elements = display_correspondence.display_elements(handle.binding_id)
        assert elements is not None
        self.elements = elements
        self.correspondence = display_correspondence.correspondence(elements, scene.stage, bindings.published_plans)
        self.view_layer = bpy.data.scenes["Scene"].view_layers[0]

    def indices(self, target: str) -> list[int]:
        return memoryview(self.correspondence.highlight_targets([target])).tolist()

    def obj(self, path: str) -> bpy.types.Object:
        return self.elements.objects[self.elements.source_paths.index(path)]

    def selected(self) -> set[str]:
        return {
            path
            for obj, path in zip(self.elements.objects, self.elements.source_paths, strict=True)
            if obj.select_get(view_layer=self.view_layer)
        }


@pytest.fixture
def display(bindings: Bindings, tmp_path: Path) -> Iterator[_Display]:
    with interaction.kind_hierarchy(tmp_path) as scene:
        yield _Display(bindings, scene)


def _unmanaged(name: str, *, selected: bool) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, None)
    bpy.data.scenes["Scene"].collection.objects.link(obj)
    obj.select_set(selected)
    return obj


def test_targets_are_selected_and_the_rest_deselected(display: _Display) -> None:
    # ICON-27: after apply_selection, the objects of the target's elements are selected and the display's others not,
    # whatever was selected before.
    for obj in display.elements.objects:
        obj.select_set(True)
    chair = display.indices(CHAIR)
    blender_selection.apply_selection(display.elements, display.view_layer, chair, [])
    assert display.selected() == {SEAT, BACK, LEGS}
    blender_selection.apply_selection(display.elements, display.view_layer, display.indices(TOP), [])
    assert display.selected() == {TOP}


def test_the_active_entry_is_active_only_with_one_object(display: _Display) -> None:
    # ICON-28: an active entry with one object makes it the active object; one with several, Chair's component, selects
    # them all and leaves no object active, though one of the display's was.
    top = display.indices(TOP)
    blender_selection.apply_selection(display.elements, display.view_layer, top, top)
    assert display.view_layer.objects.active == display.obj(TOP)
    chair = display.indices(CHAIR)
    blender_selection.apply_selection(display.elements, display.view_layer, chair, chair)
    assert display.selected() == {SEAT, BACK, LEGS}
    assert display.view_layer.objects.active is None


def test_unmanaged_objects_keep_their_selection(display: _Display) -> None:
    # ICON-29: apply_selection leaves the selection of unmanaged objects as it was, and an unmanaged active object
    # active when the active entry has several objects.
    kept, unselected = _unmanaged("Kept", selected=True), _unmanaged("Unselected", selected=False)
    display.view_layer.objects.active = kept
    chair = display.indices(CHAIR)
    blender_selection.apply_selection(display.elements, display.view_layer, chair, chair)
    assert kept.select_get() and not unselected.select_get()
    assert display.view_layer.objects.active == kept
    blender_selection.apply_selection(display.elements, display.view_layer, [], [])
    assert kept.select_get() and not unselected.select_get()


def test_reading_gives_the_selected_and_active_elements(display: _Display) -> None:
    # ICON-30: read_blender_selection gives the display's selected objects' elements and its active one's, and
    # selection_from_blender gives their targets at the level.
    for obj in (display.obj(SEAT), display.obj(TOP)):
        obj.select_set(True)
    display.view_layer.objects.active = display.obj(TOP)
    _unmanaged("Other", selected=True)
    selection = blender_selection.read_blender_selection(display.elements, display.view_layer)
    index = display.elements.source_paths.index
    assert selection.selected_element_indices == tuple(sorted((index(SEAT), index(TOP))))
    assert selection.active_element_index == index(TOP)
    targets = display.correspondence.selection_from_blender(
        selection.selected_element_indices, selection.active_element_index, "component"
    )
    assert set(targets.target_paths) == {CHAIR, "/World/Table"}
    assert targets.active_target_path == "/World/Table"


def test_objects_a_view_layer_cant_select_stay_unselected(display: _Display) -> None:
    # Blender selects only what a view layer holds and shows: in a view layer excluding the destination, and for an
    # object hidden in the viewport, apply_selection selects nothing and raises nothing.
    other = bpy.data.scenes["Scene"].view_layers.new("Other")
    other.layer_collection.children["Shot"].exclude = True
    every = range(len(display.elements.objects))
    blender_selection.apply_selection(display.elements, other, every, [])
    assert not blender_selection.read_blender_selection(display.elements, other).selected_element_indices
    display.obj(TOP).hide_viewport = True
    display.view_layer.update()
    blender_selection.apply_selection(
        display.elements, display.view_layer, [display.elements.source_paths.index(TOP)], []
    )
    assert TOP not in display.selected()


def test_mirroring_an_unchanged_selection_again_leaves_blender_nothing_to_update(display: _Display) -> None:
    # Only objects whose selection changes are set, and the active object only when it changes: setting either again
    # costs Blender a depsgraph update all the same, as after each frame change during playback. The update handler
    # fires exactly when there is something to update.
    fired: list[None] = []

    def updated(*_args: object) -> None:
        fired.append(None)

    chair = display.indices(CHAIR)
    bpy.app.handlers.depsgraph_update_post.append(updated)
    try:
        for active in (chair, display.indices(TOP)[:1]):  # several targets, then one, which becomes the active object
            blender_selection.apply_selection(display.elements, display.view_layer, chair + active, active)
            display.view_layer.update()
            assert fired, "the first mirror changes the selection"
            fired.clear()
            blender_selection.apply_selection(display.elements, display.view_layer, chair + active, active)
            display.view_layer.update()
            assert not fired
    finally:
        bpy.app.handlers.depsgraph_update_post.remove(updated)
