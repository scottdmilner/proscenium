"""The batched display's Python display component (M4, Phase D): Blender's selection state, to and from elements.

batch.py's counterparts of selection.py's functions, and the pick resolution an instance needs:
- **Partial coverage:** none arises. Each batch has a carrier per selection state, which instances only the
  points in that state, so `apply_selection` moves a selection's instances onto the selected and active carriers
  and selects exactly those. Each object then shows elements wholly in or out of the selection.
- **What a pick supplies (Q2):** what a ray cast returns, the hit object and its world matrix. For an instance,
  that is the prototype and the instance's matrix, so the instance is the batch's point whose world transform it
  is. Blender's own selection tools select a whole carrier, all the instances in its state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy
from batch import STATE, TRANSFORM
from selection import ELEMENT, BlenderSelection

if TYPE_CHECKING:
    from collections.abc import Collection

    import bpy
    from batch import Batch, BatchedDisplay
    from mathutils import Matrix

# How far a hit's world matrix may be from its instance's, against the matrix's largest entry: float32's.
MATRIX_TOLERANCE = 1e-5
SELECTED, ACTIVE = 1, 2


def managed(display: BatchedDisplay) -> list[bpy.types.Object]:
    """The display's objects: those kept as objects, and every carrier."""
    return [*display.objects.values(), *(carrier for batch in display.batches for carrier in batch.carriers)]


def states(batch: Batch) -> numpy.ndarray:
    """Each point's selection state, in point order."""
    held = numpy.empty(len(batch.elements), dtype=numpy.int32)
    _data(batch.points.attributes[STATE]).foreach_get("value", held)
    return held


def pick_element(display: BatchedDisplay, obj: bpy.types.Object, matrix: Matrix) -> int | None:
    """The element a ray cast hit, from the object and world matrix it returns; None if it isn't the display's."""
    if ELEMENT in obj:
        return obj[ELEMENT]
    batch = next((b for b in display.batches if b.prototype.as_pointer() == obj.as_pointer()), None)
    if batch is None:
        return None
    transforms = numpy.empty((len(batch.elements), 4, 4), dtype=numpy.float32)
    _data(batch.points.attributes[TRANSFORM]).foreach_get("value", transforms.ravel())
    hit = numpy.array(matrix, dtype=numpy.float64)
    best, distance = None, numpy.inf
    for carrier in batch.carriers:
        # A point's transform is USD's row-vector matrix, so Blender's is its transpose.
        worlds = numpy.array(carrier.matrix_world) @ transforms.transpose(0, 2, 1)
        errors = numpy.abs(worlds - hit).max(axis=(1, 2))
        point = int(errors.argmin())
        if errors[point] < distance:
            best, distance = point, errors[point]
    if best is None or distance > MATRIX_TOLERANCE * max(1.0, float(numpy.abs(hit).max())):
        return None
    return batch.elements[best]


def apply_selection(
    view_layer: bpy.types.ViewLayer, display: BatchedDisplay, targets: Collection[int], active: Collection[int]
) -> None:
    """Mirror display targets into Blender, as selection.apply_selection does, moving points between carriers.

    Each batch's points move onto the carrier of their state: the active entry's, the rest of the selection's, or
    neither's.
    """
    showing = []  # the active entry's display objects
    for element, obj in display.objects.items():
        obj.select_set(element in targets, view_layer=view_layer)
        if element in active:
            showing.append(obj)
    for batch in display.batches:
        wanted = numpy.array(
            [ACTIVE if e in active else SELECTED if e in targets else 0 for e in batch.elements], dtype=numpy.int32
        )
        if not numpy.array_equal(wanted, states(batch)):
            # Writing an attribute tags the mesh, so the carriers' instances follow.
            _data(batch.points.attributes[STATE]).foreach_set("value", wanted)
        for state, carrier in enumerate(batch.carriers):
            carrier.select_set(state != 0 and bool((wanted == state).any()), view_layer=view_layer)
        if (wanted == ACTIVE).any():
            showing.append(batch.carriers[ACTIVE])
    objects = managed(display)
    if len(showing) == 1:
        view_layer.objects.active = showing[0]
    elif view_layer.objects.active in objects:
        view_layer.objects.active = None


def read_blender_selection(view_layer: bpy.types.ViewLayer, display: BatchedDisplay) -> BlenderSelection:
    """The elements the selected objects show, and one the active object shows, if it is the display's.

    A carrier shows the elements in its state. An active carrier showing several gives the first of them.
    """
    current = view_layer.objects.active
    selected: set[int] = set()
    active = None
    for element, obj in display.objects.items():
        if obj.select_get(view_layer=view_layer):
            selected.add(element)
        if obj == current:
            active = element
    for batch in display.batches:
        held = states(batch)
        for state, carrier in enumerate(batch.carriers):
            shown = [e for e, s in zip(batch.elements, held, strict=True) if s == state]
            if carrier.select_get(view_layer=view_layer):
                selected.update(shown)
            if carrier == current and shown:
                active = shown[0]
    return BlenderSelection(sorted(selected), active)


def _data(attribute: bpy.types.Attribute) -> Any:
    return attribute.data  # ty: ignore[unresolved-attribute] - Attribute.data is missing from the stubs
