"""Blender's selection of a binding's display elements, mirrored and read (interaction-contract.md#blender-selection).

The display component's apply_selection and read_blender_selection, ported from the bridge's
object_display_selection.py, with elements named by their indices in DisplayElements rather than by a plan index on
each object. Each object shows one display element, so none is ever partly selected. Neither function reads the
source. Blender selects only objects its view layer holds and shows: an object hidden at the frame shown, or in a
collection that is unselectable or excluded from the view layer, stays unselected, and Blender deselects an object
when a keyed hide flag hides it, so callers mirror again when the frame shown changes (DECISIONS.md "Headless
interaction functions").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection

    import bpy

    from .display_correspondence import DisplayElements


@dataclass(frozen=True)
class BlenderSelection:
    """The selected and active managed objects of a binding's display, by element index."""

    selected_element_indices: tuple[int, ...]  # ascending
    active_element_index: int | None  # the active object's, when it is one of the display's


def _select(obj: bpy.types.Object, selected: bool, view_layer: bpy.types.ViewLayer) -> None:
    """Set the object's selection in the view layer; nothing for an object the view layer doesn't hold."""
    try:
        obj.select_set(selected, view_layer=view_layer)
    except RuntimeError:  # not in the view layer, as when its collection is excluded there
        pass


def apply_selection(
    elements: DisplayElements,
    view_layer: bpy.types.ViewLayer,
    element_indices: Collection[int],
    active_element_indices: Collection[int],
) -> None:
    """Mirror display targets into the view layer: the elements' objects selected, the display's others deselected.

    active_element_indices are the active entry's display targets: with exactly one, its object becomes the active
    object; otherwise an active object of the display's stops being active, and an unmanaged one stays. Objects that
    aren't the display's keep their selection (ICON-27 to ICON-29).
    """
    # Only the display's objects whose selection changes are set: Blender's list of the view layer's selected objects
    # is short, where setting every object costs one call each (runtime-record.md#the-products-interaction-m7-phase-g).
    indices = elements.element_indices_by_object
    selected_now = {obj for obj in view_layer.objects.selected if obj in indices}
    targets = {elements.objects[index] for index in element_indices}
    for obj in selected_now - targets:
        _select(obj, False, view_layer)
    for obj in targets - selected_now:
        _select(obj, True, view_layer)
    if len(active_element_indices) == 1:
        active = elements.objects[next(iter(active_element_indices))]
        if active.select_get(view_layer=view_layer):  # held and shown by the view layer
            if view_layer.objects.active != active:  # assigning it again costs a depsgraph update all the same
                view_layer.objects.active = active
            return
    if view_layer.objects.active in indices:
        view_layer.objects.active = None


def read_blender_selection(elements: DisplayElements, view_layer: bpy.types.ViewLayer) -> BlenderSelection:
    """The elements of the display's selected objects in the view layer, and of its active object if it is one."""
    indices = elements.element_indices_by_object
    selected = tuple(sorted(indices[obj] for obj in view_layer.objects.selected if obj in indices))
    current = view_layer.objects.active
    return BlenderSelection(selected, None if current is None else indices.get(current))
