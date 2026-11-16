"""A binding's display elements and correspondence, from its manifest and Blender data.

DECISIONS.md "Persisted correspondence": the display elements are the objects the binding's manifest names in a drawn
copy's object role, a copy's second object included, ordered by their identities, so an element's index doesn't depend
on how the manifest was written. Each element's viewport participation is its object's viewport hide flag as Blender
holds it, which keys set at the frame shown, so the correspondence answers for the time code the display shows, a
cached one included (XFORM-14). Each copy's instance context comes from the held plan of the generation shown, where it
holds the copy, and otherwise the core derives it from the copy's path on the live stage (ICON-35). Everything is read
when called and nothing is held, so a file load, undo, or redo needs nothing done.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

import bpy

from ..binding.persistence import binding_state, id_property_records, manifests
from ..binding.runtime import binding_operations, kept_manifests
from ..core import _core

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pxr import Usd

    from ..binding.runtime import held_plans
    from ..binding.source_access import BindingId


@dataclass(frozen=True)
class DisplayElements:
    """A binding's display elements, each by its element index in every tuple; none reads the source."""

    generation: binding_state.GenerationMetadata  # the record of the generation the destination shows
    entry_keys: tuple[str, ...]  # its object's manifest entry key, which survives republishing for a kept resource
    objects: tuple[bpy.types.Object, ...]
    source_paths: tuple[str, ...]  # its copy's source entity: an instance-proxy or point-instance path
    visible_in_viewport: tuple[bool, ...]  # its object's viewport hide flag shows it

    def __post_init__(self) -> None:
        columns = (self.entry_keys, self.objects, self.source_paths, self.visible_in_viewport)
        if len({len(column) for column in columns}) > 1:
            raise ValueError("Each display element needs an entry key, an object, a source path, and participation")

    @functools.cached_property
    def element_indices_by_object(self) -> Mapping[bpy.types.Object, int]:
        """Each element's index, by its object; built once, since a kept display's elements serve many calls."""
        return MappingProxyType({obj: index for index, obj in enumerate(self.objects)})


def display_elements(binding_id: BindingId) -> DisplayElements | None:
    """The binding's display elements; None for one not usable, or without a generation or a readable manifest."""
    found = binding_operations.find_binding(binding_id)
    if found is None or not found.usable or found.destination is None:
        return None
    generation = binding_state.read_generation(found.destination)
    manifest = kept_manifests.read_manifest(found.destination)
    if not isinstance(generation, id_property_records.LoadedRecord) or not isinstance(
        manifest, id_property_records.LoadedRecord
    ):
        return None
    shown: list[tuple[manifests.CopyResourceIdentity, str, bpy.types.Object]] = []
    for key, entry in manifest.record.entries.items():
        identity = entry.identity
        if entry.role is manifests.RepresentationRole.OBJECT and identity is not None:
            if isinstance(obj := entry.datablock, bpy.types.Object):  # None once the user deletes it
                shown.append((identity, key, obj))
    shown.sort(key=lambda element: element[0])
    objects = tuple(obj for _, _, obj in shown)
    return DisplayElements(
        generation=generation.record,
        entry_keys=tuple(key for _, key, _ in shown),
        objects=objects,
        source_paths=tuple(identity.entity for identity, _, _ in shown),
        visible_in_viewport=tuple(not obj.hide_viewport for obj in objects),
    )


def correspondence(
    elements: DisplayElements, live_stage: Usd.Stage | None, published_plans: held_plans.HeldPlans
) -> _core.Correspondence:
    """The core's correspondence over elements on the live stage.

    Each element's instance context is the shown generation's held plan's, where it holds the element's copy. Raises
    _core.SourceUnavailableError without a live stage, or for an expired one.
    """
    contexts: dict[str, tuple[str, ...]] = {}
    if (plan := published_plans.plan_for(elements.generation)) is not None:
        contexts = {entry.source_path: entry.instance_context for entry in plan.correspondence}
    return _core.Correspondence(
        live_stage,
        elements.source_paths,
        [contexts.get(path) for path in elements.source_paths],
        elements.visible_in_viewport,
    )
