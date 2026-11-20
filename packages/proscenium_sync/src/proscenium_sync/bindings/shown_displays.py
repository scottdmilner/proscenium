"""A binding's shown display, its elements and correspondence, kept between interaction calls while it holds.

Built for each call, a display's correspondence cost 85 ms on ALab, over M4's 50 ms budget for a pick, most of it
reading the manifest (runtime-record.md#the-products-interaction-m7-phase-g). So `ShownDisplays` keeps each binding's,
and a call reuses it while everything it was built from is as it was: the generation the destination shows, by its
record, which a synchronization or a cache call changes; the held plan for it, which gives the instance contexts; the
source revision, which advances on an attachment, a reload that changes a layer, and any change the binding's evaluation
stage sees, so instance contexts derived on the live stage follow it (DECISIONS.md "Persisted correspondence"); and each
element's object and viewport hide flag, read at every call, so participation is the flags' at the frame shown. Changed
hide flags rebuild only the planner's correspondence, and a removed object everything. A generation with no held plan,
as after reopening or an undo past the held plans, keeps nothing: its evaluation stage may not exist to advance the
revision. A released binding has no live stage, so its calls raise. The synchronizer's registration clears what's kept
after an undo, a redo, or a file load (Bindings.clear_shown_displays), which may free the objects it names.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from proscenium_sync import planner
from proscenium_sync.interaction import display_correspondence
from proscenium_sync.persistence import binding_state, id_property_records
from proscenium_sync.runtime import binding_operations
from proscenium_sync.source_access import stages

if TYPE_CHECKING:
    from collections.abc import Iterable

    import bpy
    from pxr import Usd

    from proscenium_sync.runtime import held_plans
    from proscenium_sync.source_access import BindingId


@dataclasses.dataclass(frozen=True, slots=True)
class ShownDisplay:
    """A binding's display elements and correspondence."""

    elements: display_correspondence.DisplayElements | None  # None while nothing is published
    correspondence: planner.Correspondence

    def objects(self, element_indices: Iterable[int]) -> list[bpy.types.Object]:
        """The objects of the elements at those indices, in that order."""
        assert self.elements is not None
        return [self.elements.objects[i] for i in element_indices]


@dataclasses.dataclass(frozen=True, slots=True)
class _KeptDisplay:
    shown: ShownDisplay
    elements: display_correspondence.DisplayElements  # shown's, never None
    held_plan: planner.Plan  # the plan held for the generation shown when it was built
    source_revision: stages.SourceRevision


class ShownDisplays:
    """Each binding's shown display, kept between calls while what it was built from is unchanged."""

    _kept_by_binding: dict[BindingId, _KeptDisplay]

    def __init__(self) -> None:
        self._kept_by_binding = {}

    def clear(self) -> None:
        """Keep no binding's display, so the next call of each builds it."""
        self._kept_by_binding.clear()

    def forget(self, binding_id: BindingId) -> None:
        """Keep no display of the binding, as once it's removed."""
        self._kept_by_binding.pop(binding_id, None)

    def shown(
        self,
        binding_id: BindingId,
        live: Usd.Stage | None,
        published_plans: held_plans.HeldPlans,
        binding_stages: stages.BindingStages | None,
    ) -> ShownDisplay:
        """The binding's display as it is now, kept or built; SourceUnavailableError without its live stage.

        live is the binding's live stage, published_plans the process's held plans, and binding_stages the binding's
        stages, whose source revision a kept display was built at.
        """
        if live is None:
            self._kept_by_binding.pop(binding_id, None)
            raise stages.SourceUnavailableError(f"Binding {binding_id} has no live stage")
        kept = self._kept_by_binding.get(binding_id)
        if kept is not None and _builds_from(kept, binding_id, published_plans, binding_stages):
            try:
                flags = tuple(not obj.hide_viewport for obj in kept.elements.objects)
            except ReferenceError:  # an object was removed, so the manifest no longer names it
                flags = None
            if flags == kept.elements.visible_in_viewport:
                return kept.shown
            if flags is not None:  # only participation changed
                elements = dataclasses.replace(kept.elements, visible_in_viewport=flags)
                return self._keep(binding_id, elements, live, published_plans, binding_stages)
        self._kept_by_binding.pop(binding_id, None)
        elements = display_correspondence.display_elements(binding_id)
        # The binding holds its live stage until released, so it can't expire during the call.
        if elements is None:
            return ShownDisplay(None, planner.Correspondence(live, (), (), ()))
        return self._keep(binding_id, elements, live, published_plans, binding_stages)

    def _keep(
        self,
        binding_id: BindingId,
        elements: display_correspondence.DisplayElements,
        live: Usd.Stage,
        published_plans: held_plans.HeldPlans,
        binding_stages: stages.BindingStages | None,
    ) -> ShownDisplay:
        shown = ShownDisplay(elements, display_correspondence.correspondence(elements, live, published_plans))
        held_plan = published_plans.plan_for(elements.generation)
        if held_plan is not None and binding_stages is not None:
            self._kept_by_binding[binding_id] = _KeptDisplay(shown, elements, held_plan, binding_stages.source_revision)
        return shown


def _builds_from(
    kept: _KeptDisplay,
    binding_id: BindingId,
    published_plans: held_plans.HeldPlans,
    binding_stages: stages.BindingStages | None,
) -> bool:
    """Whether what kept was built from is unchanged but its objects and their hide flags."""
    if binding_stages is None or binding_stages.source_revision != kept.source_revision:
        return False
    found = binding_operations.find_binding(binding_id)
    if found is None or not found.usable or found.destination is None:
        return False
    generation = binding_state.read_generation(found.destination)
    if not isinstance(generation, id_property_records.LoadedRecord) or generation.record != kept.elements.generation:
        return False
    return published_plans.plan_for(generation.record) is kept.held_plan
