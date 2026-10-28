"""Isolated body: support/interaction_checks.py's checks on M4's object baseline, M1b's bridge and its apply.py.

Runs in a fresh process (isolated/harness.py); see tests/isolated/test_interaction.py. The body builds the
interaction fixture itself, so its stage is the live stage the functions read.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import bpy

from fixtures import interaction
from support.interaction_checks import CHECKS, Entity, NotApplicableError, Resolved, SourceSelection

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pxr import Usd

BRIDGE = Path(__file__).resolve().parents[3] / "tools/feasibility/hydra_bridge"
FIXTURES = {
    "kind_hierarchy": interaction.kind_hierarchy,
    "nested_selection": interaction.nested_selection,
    "universe_membership": interaction.universe_membership,
}


class BaselineDisplay:
    """The baseline as a support.interaction_checks.Display: one Blender object per drawn copy and destination.

    A pick supplies the object, which names its display element (`proscenium_element`), and display targets are
    elements. What an object shows is the source apply.py recorded on it when it is in the viewport, which B1
    checks against USD.
    """

    stage: Usd.Stage
    view_layer: bpy.types.ViewLayer
    collection: bpy.types.Collection

    def __init__(self, module_dir: str, stage: Usd.Stage) -> None:
        sys.path[:0] = [str(BRIDGE), module_dir]
        self._native = importlib.import_module("_hydra_bridge")
        self._apply = importlib.import_module("apply")
        self._selection = importlib.import_module("selection")
        self.stage = stage
        self._bridge = self._native.Bridge(stage)
        scene: Any = bpy.context.scene  # never None in a running Blender
        self.view_layer = scene.view_layers[0]
        self.collection = bpy.data.collections.new("Baseline")
        scene.collection.children.link(self.collection)
        self._interaction: Any = None
        self._objects: list[bpy.types.Object] = []

    def publish(self, time: float) -> None:
        for obj in self._objects:
            bpy.data.objects.remove(obj)
        plan = self._native.build_plan(self._bridge.capture(time))
        errors = [d for d in plan.diagnostics if d["severity"] == "error"]
        assert not errors, errors
        self._objects = self._apply.apply(plan, self.collection).objects
        self._interaction = self._native.Interaction(self.stage, plan)

    def managed_objects(self) -> list[bpy.types.Object]:
        return list(self._selection.managed(self.collection).values())

    def picks(self, obj: bpy.types.Object) -> list[Any]:
        return [] if obj.hide_viewport else [obj[self._selection.ELEMENT]]

    def coverage(self, obj: bpy.types.Object) -> frozenset[str]:
        return frozenset() if obj.hide_viewport else frozenset({obj["proscenium_source"]})

    def covered(self, display_targets: Any) -> list[frozenset[str]]:
        objects = self._selection.managed(self.collection)
        return [self.coverage(objects[element]) for element in display_targets]

    def resolve_pick(self, pick: Any) -> Resolved:
        resolved = self._interaction.resolve_pick(pick)
        return Resolved(Entity(resolved["source"], tuple(resolved["instance_context"])), resolved["floor"])

    def select_targets(self, entities: Sequence[Entity], level: str | None) -> list[str]:
        return self._interaction.select_targets([(e.source, e.instance_context) for e in entities], level)

    def displayed(self, paths: Sequence[str]) -> list[bool]:
        return self._interaction.displayed(paths)

    def highlight_targets(self, targets: Sequence[str]) -> Any:
        return self._interaction.highlight_targets(targets)

    def selection_from_blender(self, blender_selection: Any, level: str | None) -> SourceSelection:
        found = self._interaction.selection_from_blender(blender_selection.selected, blender_selection.active, level)
        return SourceSelection(found["targets"], found["active"])

    def apply_selection(self, display_targets: Any, active: Any) -> None:
        self._selection.apply_selection(self.view_layer, self.collection, set(display_targets), set(active))

    def read_blender_selection(self) -> Any:
        return self._selection.read_blender_selection(self.view_layer, self.collection)

    def release(self) -> None:
        self._bridge.release()


def run_check(module_dir: str, fixture: str, check: str, dest: str) -> str:
    """Run one check on one interaction fixture: "passed", or "not applicable" when the fixture has no case."""
    with FIXTURES[fixture](Path(dest)) as scene:
        display = BaselineDisplay(module_dir, scene.stage)
        try:
            CHECKS[check](display, scene)
        except NotApplicableError:
            return "not applicable"
        finally:
            display.release()
    return "passed"
