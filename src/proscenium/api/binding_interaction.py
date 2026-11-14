"""A binding's interaction functions, as the binding handle gives them (interaction-contract.md#headless-functions).

DECISIONS.md "Headless interaction functions": api/ gives callers objects and source paths, which the display
component (proscenium.interaction) maps to the core's element indices and back. Each call reads the binding's display
elements and builds its correspondence then, at the frame the target scene shows, so nothing is held between calls.
Without a live stage each raises source access's SourceUnavailableError (ICON-08); a binding with nothing published
displays nothing.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pxr import Usd

from ..binding.persistence import binding_state, id_property_records
from ..binding.runtime import binding_operations
from ..binding.source_access import stages
from ..core import _core
from ..interaction import blender_selection, display_correspondence

if TYPE_CHECKING:
    from collections.abc import Iterable

    import bpy
    from pxr import Gf

    from ..binding.source_access import BindingId, binding_settings
    from .bindings import Bindings


@dataclass(frozen=True)
class PickedEntity:
    """The source entity a pick resolves to (interaction-contract.md#picking)."""

    source_path: str  # an instance-proxy or point-instance path inside instance contents
    instance_context: tuple[str, ...]  # native-instance roots, point instancers, and points, outermost first
    floor: str  # the outermost of them, or the entity outside instance contents


@dataclass(frozen=True)
class TargetSelection:
    """The selection targets Blender's selection of a display identifies, and the active one's."""

    target_paths: tuple[str, ...]  # in the order of the selected elements, each once
    active_target_path: str | None


class ShownDisplay:
    """A binding's display elements and correspondence, read for one call."""

    elements: display_correspondence.DisplayElements | None  # None while nothing is published
    correspondence: _core.Correspondence

    def __init__(self, bindings: Bindings, binding_id: BindingId) -> None:
        live = bindings.live_stage(binding_id)
        if live is None:
            raise stages.SourceUnavailableError(f"Binding {binding_id} has no live stage")
        self.elements = display_correspondence.display_elements(binding_id)
        # The binding holds its live stage until released, so it can't expire during the call.
        if self.elements is None:
            self.correspondence = _core.Correspondence(live, (), (), ())
        else:
            self.correspondence = display_correspondence.correspondence(self.elements, live, bindings.published_plans)

    def objects(self, element_indices: Iterable[int]) -> list[bpy.types.Object]:
        """The objects of the elements at those indices, in that order."""
        assert self.elements is not None
        return [self.elements.objects[i] for i in element_indices]


def resolve_pick(
    bindings: Bindings, binding_id: BindingId, obj: bpy.types.Object, world_matrix: Gf.Matrix4d
) -> PickedEntity | None:
    """The source entity the picked object shows, or None for an object the display doesn't show."""
    shown = ShownDisplay(bindings, binding_id)
    if shown.elements is None or obj not in (indices := shown.elements.element_index_by_object()):
        return None
    entity = shown.correspondence.resolve_pick(indices[obj], world_matrix)
    return None if entity is None else PickedEntity(entity.source_path, entity.instance_context, entity.floor)


def select_targets(
    bindings: Bindings, binding_id: BindingId, entity_paths: Iterable[str], level: str | None
) -> list[str]:
    """Each entity's selection target at level: None for the prim level, or a registered kind's name."""
    shown = ShownDisplay(bindings, binding_id)
    paths = list(entity_paths)
    return list(shown.correspondence.select_targets(paths, level))


def displayed(bindings: Bindings, binding_id: BindingId, paths: Iterable[str]) -> list[bool]:
    """Whether each path is in the browsing universe at the time code the display shows."""
    shown = ShownDisplay(bindings, binding_id)
    source_paths = list(paths)
    return [bool(v) for v in memoryview(shown.correspondence.displayed(source_paths)).tolist()]


def highlight_targets(bindings: Bindings, binding_id: BindingId, target_paths: Iterable[str]) -> list[bpy.types.Object]:
    """The display's objects covering exactly the viewport elements of the targets' expanded entities."""
    shown = ShownDisplay(bindings, binding_id)
    targets = list(target_paths)
    covered = shown.correspondence.highlight_targets(targets)
    return [] if shown.elements is None else shown.objects(memoryview(covered).tolist())


def selection_from_blender(
    bindings: Bindings, binding_id: BindingId, level: str | None, view_layer: bpy.types.ViewLayer
) -> TargetSelection:
    """The targets at level of the display's objects selected in view_layer, and the active object's."""
    shown = ShownDisplay(bindings, binding_id)
    if shown.elements is None:
        return TargetSelection((), None)
    read = blender_selection.read_blender_selection(shown.elements, view_layer)
    selection = shown.correspondence.selection_from_blender(
        read.selected_element_indices, read.active_element_index, level
    )
    return TargetSelection(selection.target_paths, selection.active_target_path)


def shown_generation(binding_id: BindingId) -> tuple[binding_state.GenerationMetadata, bpy.types.Scene] | None:
    """The record of the generation the binding's destination shows, and its target scene; None without one."""
    found = binding_operations.find_binding(binding_id)
    if found is None or found.destination is None or found.scene is None:
        return None
    generation = binding_state.read_generation(found.destination)
    if not isinstance(generation, id_property_records.LoadedRecord):
        return None
    return generation.record, found.scene


def shown_time_code(binding_id: BindingId) -> Usd.TimeCode | None:
    """The time code the display shows at its target scene's frame, or None while nothing is published.

    transforms.md#transforms-and-time-codes: a time code its generation holds at its frame, and at any other frame the
    latest before it, or before the earliest, the earliest. A generation synchronized at the default time code shows it.
    """
    if (found := shown_generation(binding_id)) is None:
        return None
    generation, scene = found
    if generation.time_code is None:
        return Usd.TimeCode.Default()
    held = sorted((generation.time_code, *generation.cached_time_codes))
    frame = scene.frame_current + scene.frame_subframe
    return Usd.TimeCode(held[max(0, bisect.bisect_right(held, frame) - 1)])


def applied_settings(binding_id: BindingId) -> binding_settings.RequestedSettings | None:
    """The settings the published generation was synchronized with, or None while nothing is published."""
    return None if (found := shown_generation(binding_id)) is None else found[0].applied_settings
