"""The interaction contract on the real display: support/interaction_checks.py's checks through api/ (M7 plan, E6).

M4 wrote the checks for its prototypes (tests/isolated/test_interaction.py); here an adapter passes them the product:
a binding synchronized at each of the fixture's time codes, picks as a ray cast gives them (the object hit and its world
matrix), display targets as objects, and Blender's selection read through the handle. What an object shows comes from
the binding's manifest, the display's own record of what it built, and its viewport hide flag, never from the functions
under check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest

from fixtures import interaction
from proscenium.binding.persistence import id_property_records
from proscenium.binding.persistence.manifests import RepresentationRole
from proscenium.binding.results import ResultState
from proscenium.binding.runtime import ownership
from proscenium.binding.source_access.binding_settings import PayloadPolicy
from proscenium.interaction import blender_selection, display_correspondence
from support import interaction_oracle
from support.interaction_checks import CHECKS, NotApplicableError, ResolvedPick, SourceEntity, SourceSelection

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from pxr import Usd

    from proscenium.api.bindings import BindingHandle, Bindings

FIXTURES = {
    "kind_hierarchy": interaction.kind_hierarchy,
    "nested_selection": interaction.nested_selection,
    "universe_membership": interaction.universe_membership,
}


class ProductDisplay:
    """The product's display as an InteractionTestDisplay, one object per drawn copy."""

    stage: Usd.Stage
    view_layer: bpy.types.ViewLayer
    handle: BindingHandle

    def __init__(self, bindings: Bindings, stage: Usd.Stage) -> None:
        self.stage = stage
        target = bpy.data.scenes["Scene"]
        self.view_layer = target.view_layers[0]
        # The load-none policy keeps F-UNIVERSE-MEMBERSHIP's payload unloaded, as the caller's stage has it; the other
        # fixtures have no payloads.
        self.handle = bindings.create_binding(target, payload_policy=PayloadPolicy.LOAD_NONE, name="Shot")
        assert self.handle.attach(stage).state is not ResultState.FATAL_FAILURE

    def publish(self, time: float) -> None:
        assert self.handle.synchronize(time).state is not ResultState.FATAL_FAILURE

    def _sources(self) -> dict[bpy.types.Object, str]:
        """Each object the manifest names in the object role, and its source entity."""
        manifest = ownership.manifest(self.handle.binding_id)
        assert isinstance(manifest, id_property_records.LoadedRecord)
        return {
            obj: e.source_entity_paths[0]
            for e in manifest.record.entries.values()
            if e.role is RepresentationRole.OBJECT and isinstance(obj := e.datablock, bpy.types.Object)
        }

    def managed_objects(self) -> list[bpy.types.Object]:
        return list(self._sources())

    def picks(self, obj: bpy.types.Object) -> list[Any]:
        return [] if obj.hide_viewport else [(obj, obj.matrix_world.copy())]

    def coverage(self, obj: bpy.types.Object) -> frozenset[str]:
        return frozenset() if obj.hide_viewport else frozenset({self._sources()[obj]})

    def covered(self, display_targets: Any) -> list[frozenset[str]]:
        return [self.coverage(obj) for obj in display_targets]

    def resolve_pick(self, pick: Any) -> ResolvedPick:
        picked = self.handle.resolve_pick(*pick)
        assert picked is not None
        return ResolvedPick(SourceEntity(picked.source_path, picked.instance_context), picked.floor)

    def select_targets(self, entities: Sequence[SourceEntity], level: str | None) -> list[str]:
        return self.handle.select_targets([e.source_path for e in entities], level)

    def displayed(self, paths: Sequence[str]) -> list[bool]:
        return self.handle.displayed(paths)

    def highlight_targets(self, targets: Sequence[str]) -> Any:
        return self.handle.highlight_targets(targets)

    def selection_from_blender(self, blender_selection: Any, level: str | None) -> SourceSelection:
        del blender_selection  # the handle reads Blender's selection itself
        found = self.handle.selection_from_blender(level, self.view_layer)
        return SourceSelection(list(found.target_paths), found.active_target_path)

    def apply_selection(self, display_targets: Any, active: Any) -> None:
        elements = display_correspondence.display_elements(self.handle.binding_id)
        assert elements is not None
        indices = elements.element_index_by_object()
        blender_selection.apply_selection(
            elements, self.view_layer, [indices[o] for o in display_targets], [indices[o] for o in active]
        )

    def read_blender_selection(self) -> Any:
        return None  # selection_from_blender reads it


@pytest.mark.parametrize("check", list(CHECKS))
@pytest.mark.parametrize("fixture", list(FIXTURES))
def test_interaction(bindings: Bindings, tmp_path: Path, fixture: str, check: str) -> None:
    # The rows each check names (support/interaction_checks.py), on the real display: INSP-01, INSP-02, ICON-10 to
    # ICON-15, ICON-17 to ICON-23, ICON-27 to ICON-30, and ICON-06, at each of the fixture's time codes.
    with FIXTURES[fixture](tmp_path) as scene:
        try:
            CHECKS[check](ProductDisplay(bindings, scene.stage), scene)
        except NotApplicableError:
            pytest.skip(f"{fixture} has no case for {check}")


def test_inspection_ignores_blender_parenting_and_names(bindings: Bindings, tmp_path: Path) -> None:
    # INSP-03 on F-KIND-HIERARCHY: after the managed objects are reparented to an unmanaged object, then half of them
    # unparented, and each renamed to another's name, resolve_pick, displayed, and highlight_targets answer as before.
    with interaction.kind_hierarchy(tmp_path) as scene:
        display = ProductDisplay(bindings, scene.stage)
        display.publish(0.0)
        handle = display.handle
        objects = display.managed_objects()
        paths = interaction_oracle.all_paths(scene.stage)

        def answers() -> tuple[object, ...]:
            picks = [handle.resolve_pick(*pick) for obj in objects for pick in display.picks(obj)]
            highlights = [set(handle.highlight_targets([p])) for p in paths]
            return picks, handle.displayed(paths), highlights

        before = answers()
        parent = bpy.data.objects.new("UnmanagedParent", None)
        parent.location = (5.0, -3.0, 2.0)
        bpy.data.scenes["Scene"].collection.objects.link(parent)
        for obj in objects:
            obj.parent = parent
        assert answers() == before
        for obj in objects[::2]:
            obj.parent = None
        names = [obj.name for obj in objects]
        for obj in objects:
            obj.name = f"Renamed {obj.name}"
        for obj, name in zip(objects, names[1:] + names[:1], strict=True):
            obj.name = name
        assert answers() == before
