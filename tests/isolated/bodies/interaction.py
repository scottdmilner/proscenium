"""Isolated body: support/interaction_checks.py's checks on M4's display representations.

The object baseline (apply.py) and Phase D's batched display (batch.py). Runs in a fresh process
(isolated/harness.py); see tests/isolated/test_interaction.py. The body builds the interaction fixture itself, so
its stage is the live stage the functions read.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

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


class BatchedDisplay(BaselineDisplay):
    """Phase D's batched display (batch.py) as a Display: carriers of instances beside the objects kept as objects.

    A pick supplies what a ray cast returns, the hit object and its world matrix: for an instance, its prototype
    and the instance's matrix as Blender evaluates it. What a carrier shows is the elements Blender evaluates it
    to instance, so the mirroring checks see each carrier's coverage as drawn, not as batch_selection.py set it.
    """

    def __init__(self, module_dir: str, stage: Usd.Stage) -> None:
        super().__init__(module_dir, stage)
        self._batch = importlib.import_module("batch")
        self._batched = importlib.import_module("batch_selection")
        self._display: Any = None
        self._records: list[Any] = []

    @override
    def publish(self, time: float) -> None:
        if self._display is not None:
            prototypes = [batch.prototype for batch in self._display.batches]
            bpy.data.batch_remove([*self._batched.managed(self._display), *prototypes])
        plan = self._native.build_plan(self._bridge.capture(time))
        errors = [d for d in plan.diagnostics if d["severity"] == "error"]
        assert not errors, errors
        self._display = self._batch.apply_batched(plan, self.collection)
        self._records = plan.objects
        self._interaction = self._native.Interaction(self.stage, plan)

    @override
    def managed_objects(self) -> list[bpy.types.Object]:
        return self._batched.managed(self._display)

    def _kept(self, obj: bpy.types.Object) -> bool:
        return any(obj == kept for kept in self._display.objects.values())

    def _drawn(self, carrier: bpy.types.Object) -> list[tuple[int, bpy.types.Object, Any]]:
        """The instances Blender evaluates `carrier` to: each one's element, prototype, and world matrix."""
        if carrier.hide_viewport:
            return []
        self.view_layer.update()
        depsgraph: Any = self.view_layer.depsgraph  # never None once updated
        geometry = carrier.evaluated_get(depsgraph).evaluated_geometry()
        instances = geometry.instances_pointcloud()  # None for a carrier with no instances
        if instances is None:
            return []
        elements = [e.value for e in instances.attributes[self._selection.ELEMENT].data]
        return [
            # The instance's index in its carrier's instances is persistent_id[1] (ad hoc, Blender 5.2).
            (elements[i.persistent_id[1]], i.instance_object.original, i.matrix_world.copy())
            for i in depsgraph.object_instances
            if i.is_instance and i.parent is not None and i.parent.original == carrier
        ]

    @override
    def picks(self, obj: bpy.types.Object) -> list[Any]:
        if self._kept(obj):
            return [] if obj.hide_viewport else [(obj, obj.matrix_world.copy())]
        return [(prototype, matrix) for _, prototype, matrix in self._drawn(obj)]

    @override
    def coverage(self, obj: bpy.types.Object) -> frozenset[str]:
        if self._kept(obj):
            return super().coverage(obj)
        return frozenset(self._records[element]["source"] for element, _, _ in self._drawn(obj))

    @override
    def covered(self, display_targets: Any) -> list[frozenset[str]]:
        records = self._records
        return [frozenset({records[e]["source"]}) if records[e]["viewport"] else frozenset() for e in display_targets]

    @override
    def resolve_pick(self, pick: Any) -> Resolved:
        element = self._batched.pick_element(self._display, *pick)
        assert element is not None, pick
        return super().resolve_pick(element)

    @override
    def apply_selection(self, display_targets: Any, active: Any) -> None:
        self._batched.apply_selection(self.view_layer, self._display, set(display_targets), set(active))

    @override
    def read_blender_selection(self) -> Any:
        return self._batched.read_blender_selection(self.view_layer, self._display)


DISPLAYS = {"objects": BaselineDisplay, "batched": BatchedDisplay}


def run_check(module_dir: str, fixture: str, check: str, dest: str, representation: str = "objects") -> str:
    """Run one check on one interaction fixture: "passed", or "not applicable" when the fixture has no case."""
    with FIXTURES[fixture](Path(dest)) as scene:
        display = DISPLAYS[representation](module_dir, scene.stage)
        try:
            CHECKS[check](display, scene)
        except NotApplicableError:
            return "not applicable"
        finally:
            display.release()
    return "passed"
