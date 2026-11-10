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
from pxr import Usd

from fixtures import appearance, interaction
from support.interaction_checks import CHECKS, NotApplicableError, ResolvedPick, SourceEntity, SourceSelection

if TYPE_CHECKING:
    from collections.abc import Sequence

BRIDGE = Path(__file__).resolve().parents[3] / "tools/feasibility/hydra_bridge"
FIXTURES = {
    "kind_hierarchy": interaction.kind_hierarchy,
    "nested_selection": interaction.nested_selection,
    "universe_membership": interaction.universe_membership,
}


class BaselineDisplay:
    """The object baseline as an InteractionTestDisplay, one object per drawn copy and destination.

    A pick supplies the object, which names its display element (`proscenium_element`), and display targets are
    elements. What an object shows is the source apply.py recorded on it when it is in the viewport, which B1
    checks against USD.
    """

    stage: Usd.Stage
    view_layer: bpy.types.ViewLayer
    collection: bpy.types.Collection
    point_instancers: bool  # the plan setting that translates point instancers' instances (D6)

    def __init__(self, module_dir: str, stage: Usd.Stage, point_instancers: bool = True) -> None:
        sys.path[:0] = [str(BRIDGE), module_dir]
        self._native = importlib.import_module("_hydra_bridge")
        self._apply = importlib.import_module("apply")
        self._selection = importlib.import_module("selection")
        self.stage = stage
        self.point_instancers = point_instancers
        self._bridge = self._native.Bridge(stage)
        scene: Any = bpy.context.scene  # never None in a running Blender
        self.view_layer = scene.view_layers[0]
        self.collection = bpy.data.collections.new("Baseline")
        scene.collection.children.link(self.collection)
        self._interaction: Any = None
        self._objects: list[bpy.types.Object] = []
        self._records: list[Any] = []

    def publish(self, time: float) -> None:
        for obj in self._objects:
            bpy.data.objects.remove(obj)
        plan = self._native.build_plan(self._bridge.capture(time), point_instancers=self.point_instancers)
        errors = [d for d in plan.diagnostics if d["severity"] == "error"]
        assert not errors, errors
        self._objects = self._apply.apply(plan, self.collection).objects
        self._records = plan.objects
        self._interaction = self._native.SourceSelectionResolver(self.stage, plan)

    def managed_objects(self) -> list[bpy.types.Object]:
        return list(self._selection.managed(self.collection).values())

    def drawn(self, element: int) -> tuple[str, list[str]]:
        """The source and instance context the plan gives `element`."""
        record = self._records[element]
        return record["source"], list(record["instance_context"])

    def elements(self, obj: bpy.types.Object) -> list[int]:
        """The display elements `obj` shows in the viewport, in the order of its picks."""
        return [] if obj.hide_viewport else [obj[self._selection.ELEMENT]]

    def picks(self, obj: bpy.types.Object) -> list[Any]:
        return [] if obj.hide_viewport else [obj[self._selection.ELEMENT]]

    def coverage(self, obj: bpy.types.Object) -> frozenset[str]:
        return frozenset() if obj.hide_viewport else frozenset({obj["proscenium_source"]})

    def covered(self, display_targets: Any) -> list[frozenset[str]]:
        objects = self._selection.managed(self.collection)
        return [self.coverage(objects[element]) for element in display_targets]

    def resolve_pick(self, pick: Any) -> ResolvedPick:
        resolved = self._interaction.resolve_pick(pick)
        return ResolvedPick(SourceEntity(resolved["source"], tuple(resolved["instance_context"])), resolved["floor"])

    def select_targets(self, entities: Sequence[SourceEntity], level: str | None) -> list[str]:
        return self._interaction.select_targets([(e.source, e.instance_context) for e in entities], level)

    def displayed(self, paths: Sequence[str]) -> list[bool]:
        return self._interaction.displayed(paths)

    def highlight_targets(self, targets: Sequence[str]) -> Any:
        return self._interaction.highlight_targets(targets)

    def selection_from_blender(self, blender_selection: Any, level: str | None) -> SourceSelection:
        found = self._interaction.selection_from_blender(
            blender_selection.selected_element_indices, blender_selection.active_element_index, level
        )
        return SourceSelection(found["targets"], found["active"])

    def apply_selection(self, display_targets: Any, active: Any) -> None:
        self._selection.apply_selection(self.view_layer, self.collection, set(display_targets), set(active))

    def read_blender_selection(self) -> Any:
        return self._selection.read_blender_selection(self.view_layer, self.collection)

    def release(self) -> None:
        self._bridge.release()


class BatchedDisplay(BaselineDisplay):
    """The batched display as an InteractionTestDisplay, with instance carriers and individual objects.

    A pick supplies what a ray cast returns, the hit object and its world matrix: for an instance, its prototype
    and the instance's matrix as Blender evaluates it. What a carrier shows is the elements Blender evaluates it
    to instance, so the mirroring checks see each carrier's coverage as drawn, not as batch_selection.py set it.
    """

    def __init__(self, module_dir: str, stage: Usd.Stage, point_instancers: bool = True) -> None:
        super().__init__(module_dir, stage, point_instancers)
        self._batch = importlib.import_module("batch")
        self._batched = importlib.import_module("batch_selection")
        self._display: Any = None

    @override
    def publish(self, time: float) -> None:
        if self._display is not None:
            prototypes = [batch.prototype for batch in self._display.batches]
            bpy.data.batch_remove([*self._batched.managed(self._display), *prototypes])
        plan = self._native.build_plan(self._bridge.capture(time), point_instancers=self.point_instancers)
        errors = [d for d in plan.diagnostics if d["severity"] == "error"]
        assert not errors, errors
        self._display = self._batch.apply_batched(plan, self.collection)
        self._records = plan.objects
        self._interaction = self._native.SourceSelectionResolver(self.stage, plan)

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
    def elements(self, obj: bpy.types.Object) -> list[int]:
        if self._kept(obj):
            return super().elements(obj)
        return [element for element, _, _ in self._drawn(obj)]

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
    def resolve_pick(self, pick: Any) -> ResolvedPick:
        element = self._batched.pick_element(self._display, *pick)
        assert element is not None, pick
        return super().resolve_pick(element)

    @override
    def apply_selection(self, display_targets: Any, active: Any) -> None:
        before = [dict(batch.carriers) for batch in self._display.batches]
        self._batched.apply_selection(self.view_layer, self._display, set(display_targets), set(active))
        # A batch has a carrier for each state its points hold, and only those. It keeps those of the states it
        # still holds, and creates objects only for states beyond its earlier number (D3).
        self.view_layer.update()  # a new carrier's world matrix is evaluated from its parent
        for batch, old in zip(self._display.batches, before, strict=True):
            carriers = batch.carriers
            assert set(carriers) == set(self._batched.states(batch).tolist()), carriers
            assert all(carriers[state] == old[state] for state in carriers.keys() & old.keys()), (carriers, old)
            fresh = [c for c in carriers.values() if all(c != o for o in old.values())]
            assert len(fresh) == max(0, len(carriers) - len(old)), (carriers, old)
            # Placed, parented, and shown alike.
            looks = {
                (c.parent, tuple(map(tuple, c.matrix_world)), c.hide_viewport, c.hide_render) for c in carriers.values()
            }
            assert len(looks) == 1, looks

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


def point_instancer_interaction(module_dir: str, dest: str, representation: str) -> dict[str, Any]:
    """Picks and selection mirroring on point-instanced copies (D6), by display element.

    Copies of one prototype mesh at different points share a source, so what each object shows is read by element.
    Reports each pick with the element drawn there, the source and instance context the plan gives it, and what
    the pick resolves to; and for a selection of every other element, the first one active, the elements the
    selected objects show and the selection read back.
    """
    with appearance.point_instancers(Path(dest)) as scene:
        display = DISPLAYS[representation](module_dir, scene.stage)
        try:
            display.publish(Usd.TimeCode.Default().GetValue())
            picks = []
            for obj in display.managed_objects():
                for element, pick in zip(display.elements(obj), display.picks(obj), strict=True):
                    resolved = display.resolve_pick(pick)
                    entity = resolved.entity
                    resolved_as = [entity.source, list(entity.instance_context)]
                    picks.append(
                        {"element": element, "drawn": list(display.drawn(element))}
                        | {"resolved": resolved_as, "floor": resolved.floor}
                    )
            shown = sorted(pick["element"] for pick in picks)
            targets, active = shown[::2], shown[:1]
            display.apply_selection(targets, active)
            view_layer = display.view_layer
            selected = [o for o in display.managed_objects() if o.select_get(view_layer=view_layer)]
            read = display.read_blender_selection()
            return {
                "picks": picks,
                "targets": targets,
                "selected": sorted(e for obj in selected for e in display.elements(obj)),
                "read": {"selected": sorted(read.selected_element_indices), "active": read.active_element_index},
            }
        finally:
            display.release()


def select_tool_session(module_dir: str, dest: str) -> list[str]:
    """The source selection tool's session (select_tool.py, F2's Q4) on F-KIND-HIERARCHY's batched display.

    Each pick supplies what a ray cast returns there: an object kept as an object, or a batch's prototype and the
    instance's world matrix. Reports where the session differs from the scene's construction: each element picked
    at each level the fixture names selects its kind target, made active, and Blender shows exactly its elements;
    set, toggle, extend, and subtract combine prim-level picks, and a pick on nothing clears the selection; each
    viewport element's center is its prim's world bounds' centroid as USD computes it; unselectable, managed objects
    hold no selection while the source selection is kept, and show it again once selectable; and Blender's own
    selection, followed, becomes the source selection selection_from_blender gives.
    """
    from pxr import UsdGeom

    with interaction.kind_hierarchy(Path(dest)) as scene:
        display = BatchedDisplay(module_dir, scene.stage)  # puts the bridge on sys.path
        select_tool = importlib.import_module("select_tool")
        try:
            display.publish(0.0)
            records = display._records  # noqa: SLF001 - the plan the display was built from
            session = select_tool.Session(
                display._interaction,
                display._display,
                display.view_layer,
                display.collection,  # noqa: SLF001
            )
            picks: dict[str, Any] = {}  # by source, a pick on one of its elements
            for obj in display.managed_objects():
                for element, pick in zip(display.elements(obj), display.picks(obj), strict=True):
                    picks.setdefault(records[element]["source"], (element, pick))
            found: list[str] = []

            def pick(source: str | None, mode: str) -> None:
                if source is None:
                    session.pick(None, None, mode)
                    return
                obj, matrix = picks[source][1] if isinstance(picks[source][1], tuple) else (None, None)
                if obj is None:  # an object kept as an object supplies itself
                    obj = next(o for o in display.managed_objects() if o.get("proscenium_element") == picks[source][0])
                    matrix = obj.matrix_world
                session.pick(obj, matrix, mode)

            def shown() -> set[int]:
                selected = [o for o in display.managed_objects() if o.select_get(view_layer=display.view_layer)]
                return {e for o in selected for e in display.elements(o)}

            for (entity, level), target in scene.kind_targets.items():
                if entity not in picks:
                    continue
                session.level = level
                pick(entity, "SET")
                if (session.targets, session.active) != ([target], target):
                    found.append(f"{entity} at {level}: {session.targets}, active {session.active}, not {target}")
                if shown() != set(display.highlight_targets([target])):
                    found.append(f"{entity} at {level}: Blender shows {sorted(shown())}")
            session.level = None
            seat, back, top = "/World/Props/Chair/Geom/Seat", "/World/Props/Chair/Geom/Back", "/World/Table/Top"
            for source, mode, targets, active in (
                (seat, "SET", [seat], seat),
                (top, "TOGGLE", [seat, top], top),
                (seat, "TOGGLE", [top], top),
                (back, "EXTEND", [top, back], back),
                (top, "SUBTRACT", [back], back),
                (back, "SUBTRACT", [], None),
                (top, "SET", [top], top),
                (None, "SET", [], None),
            ):
                pick(source, mode)
                if (session.targets, session.active) != (targets, active):
                    found.append(
                        f"{mode} {source}: {session.targets}, active {session.active}, not {targets}, {active}"
                    )
            if shown():
                found.append(f"cleared, Blender still shows {sorted(shown())}")
            # Outside the tool, managed objects are unselectable and deselected; the source selection waits.
            pick(seat, "SET")
            session.set_selectable(False)
            if not display.collection.hide_select or shown():
                found.append(f"unselectable: shows {sorted(shown())}")
            pick(back, "EXTEND")
            if session.targets != [seat, back] or shown():
                found.append(f"picked while unselectable: {session.targets}, shows {sorted(shown())}")
            session.set_selectable(True)
            if display.collection.hide_select or shown() != set(display.highlight_targets([seat, back])):
                found.append(f"selectable again: shows {sorted(shown())}")
            pick(None, "SET")
            cache = UsdGeom.BBoxCache(0.0, [UsdGeom.Tokens.default_, UsdGeom.Tokens.render, UsdGeom.Tokens.proxy])
            for element, center in session.centers().items():
                prim = scene.stage.GetPrimAtPath(records[element]["source"])
                centroid = cache.ComputeWorldBound(prim).ComputeCentroid()
                expected = [centroid[0], centroid[1], centroid[2]]
                if max(abs(a - b) for a, b in zip(center[:3], expected, strict=True)) > 1e-4:
                    found.append(f"{records[element]['source']}: center {list(center[:3])}, not {expected}")
            # Blender's own selection, followed: one object kept as an object, selected and active, at a kind level.
            kept = next(iter(display._display.objects.values()))  # noqa: SLF001
            for obj in display.managed_objects():
                obj.select_set(obj == kept, view_layer=display.view_layer)
            display.view_layer.objects.active = kept
            session.level = "component"
            expected = display.selection_from_blender(display.read_blender_selection(), "component")
            session.follow_blender()
            if (session.targets, session.active) != (list(expected.targets), expected.active):
                found.append(f"followed: {session.targets}, active {session.active}, not {expected}")
            return found
        finally:
            display.release()
