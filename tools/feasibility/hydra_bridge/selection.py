"""The baseline's Python display component (M4): Blender's selection state, to and from display elements.

The interaction contract's apply_selection and read_blender_selection. A managed object is one apply.py built,
named by the element it realizes (its plan index, `proscenium_element`). Each covers exactly one display
element, so no object is ever partly selected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection

    import bpy

ELEMENT = "proscenium_element"


@dataclass(frozen=True)
class BlenderSelection:
    """The selected and active managed objects, by element."""

    selected: list[int]  # in element order
    active: int | None  # the active object, when it is managed


def managed(collection: bpy.types.Collection) -> dict[int, bpy.types.Object]:
    """The managed objects in `collection`, by element."""
    return {obj[ELEMENT]: obj for obj in collection.objects if ELEMENT in obj}


def apply_selection(
    view_layer: bpy.types.ViewLayer,
    collection: bpy.types.Collection,
    targets: Collection[int],
    active: Collection[int],
) -> None:
    """Mirror display targets into Blender: the managed objects of `targets` are selected, the rest deselected.

    `active` holds the active entry's display targets. With exactly one, it becomes the active object; with
    several or none, no managed object stays active. Unmanaged objects keep their selection.
    """
    objects = managed(collection)
    for element, obj in objects.items():
        obj.select_set(element in targets, view_layer=view_layer)
    if len(active) == 1:
        view_layer.objects.active = objects[next(iter(active))]
    elif view_layer.objects.active in objects.values():
        view_layer.objects.active = None


def read_blender_selection(view_layer: bpy.types.ViewLayer, collection: bpy.types.Collection) -> BlenderSelection:
    """The elements of the selected managed objects, and of the active object if it is managed."""
    objects = managed(collection)
    selected = sorted(element for element, obj in objects.items() if obj.select_get(view_layer=view_layer))
    current = view_layer.objects.active
    active = next((element for element, obj in objects.items() if obj == current), None)
    return BlenderSelection(selected, active)
