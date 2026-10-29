"""Checks of a display representation's headless interaction functions against the M2 oracle (M4, B3).

Written once and reused: M4 passes each prototype's adapter, M7 and M10 the real display. A check takes a
`Display`, which publishes generations of an interaction fixture's live stage, and asserts the contract's
results (interaction-contract.md) against support/interaction_oracle.py, at every time code the fixture lists.
Each check names the matrix rows it covers.

Picks, display targets, and Blender selections are the representation's own values: the checks only pass them
back. What a Blender object or display target shows comes from the adapter's `coverage` and `covered`, which
read the representation's own record of what it built, never the functions under check. The checks use bpy
(imported inside them, so this module imports without it) and run where the display does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from support import interaction_oracle as oracle

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import bpy
    from pxr import Usd

    from fixtures.interaction import InteractionScene


@dataclass(frozen=True)
class Entity:
    """A source entity: a USD path, with the native-instance roots enclosing it, outermost first."""

    source: str
    instance_context: tuple[str, ...] = ()


@dataclass(frozen=True)
class Resolved:
    """What resolve_pick returns: the hit entity and its floor."""

    entity: Entity
    floor: str


@dataclass(frozen=True)
class SourceSelection:
    """What selection_from_blender returns."""

    targets: list[str]
    active: str | None


class NotApplicableError(Exception):
    """The fixture has no case for this check."""


class Display(Protocol):
    """A display representation under check, with its implementation of the seven headless functions."""

    @property
    def stage(self) -> Usd.Stage: ...  # the live stage
    @property
    def view_layer(self) -> bpy.types.ViewLayer: ...  # the one Blender selection is mirrored into

    def publish(self, time: float) -> None:
        """Synchronize at `time`, replacing the published generation."""

    def managed_objects(self) -> list[bpy.types.Object]:
        """The Blender objects the published generation built."""

    def picks(self, obj: bpy.types.Object) -> list[Any]:
        """What a viewport pick supplies for each display element `obj` shows there."""

    def coverage(self, obj: bpy.types.Object) -> frozenset[str]:
        """The viewport display elements `obj` shows, by the representation's record of what it built."""

    def covered(self, display_targets: Any) -> list[frozenset[str]]:
        """Per display target, the viewport display elements it covers, by the same record."""

    def resolve_pick(self, pick: Any) -> Resolved: ...
    def select_targets(self, entities: Sequence[Entity], level: str | None) -> list[str]: ...
    def displayed(self, paths: Sequence[str]) -> list[bool]: ...
    def highlight_targets(self, targets: Sequence[str]) -> Any: ...
    def selection_from_blender(self, blender_selection: Any, level: str | None) -> SourceSelection: ...
    def apply_selection(self, display_targets: Any, active: Any) -> None: ...
    def read_blender_selection(self) -> Any: ...


def entity(stage: Usd.Stage, path: str) -> Entity:
    """The entity at `path`, with its instance context from the stage."""
    return Entity(path, oracle.instance_context(stage, path))


def _generations(display: Display, scene: InteractionScene) -> Any:
    """Publish each of the fixture's generations in turn, yielding the oracle's expectations for it."""
    for time in scene.times:
        display.publish(time)
        yield oracle.generation(display.stage, time)


def check_picks(display: Display, scene: InteractionScene) -> None:
    """INSP-01, ICON-01, ICON-19: each pick resolves to the entity it hit, with instance context and floor."""
    for expected in _generations(display, scene):
        found = set()
        for obj in display.managed_objects():
            for pick in display.picks(obj):
                resolved = display.resolve_pick(pick)
                source = resolved.entity.source
                assert source in display.coverage(obj), (obj.name, source)
                assert resolved.entity == entity(display.stage, source), resolved
                assert resolved.floor == expected.floors[source], resolved
                found.add(source)
        assert found == expected.elements, expected.time


def check_picks_ignore_names_and_parenting(display: Display, scene: InteractionScene) -> None:
    """ICON-17: picks resolve to the same entities after the display objects are renamed and reparented.

    The new parent is offset, so reparenting moves every object, and a pick's own data changes with it.
    """
    import bpy

    display.publish(scene.times[0])
    objects = display.managed_objects()
    before = [[display.resolve_pick(pick) for pick in display.picks(obj)] for obj in objects]
    parent = bpy.data.objects.new("UnmanagedParent", None)
    parent.location = (5.0, -3.0, 2.0)
    _scene_collection().objects.link(parent)
    # Each takes another's name, so a lookup by name would find the wrong one.
    names = [obj.name for obj in objects]
    for obj in objects:
        obj.name = f"Renamed {obj.name}"
    for obj, name in zip(objects, names[1:] + names[:1], strict=True):
        obj.name = name
        obj.parent = parent
    assert [[display.resolve_pick(pick) for pick in display.picks(obj)] for obj in objects] == before


def check_displayed(display: Display, scene: InteractionScene) -> None:
    """ICON-11 to ICON-15, and ICON-25 and ICON-26's membership per generation: displayed is the universe."""
    for expected in _generations(display, scene):
        paths = [*oracle.all_paths(display.stage), *scene.probes]
        assert dict(zip(paths, display.displayed(paths), strict=True)) == {p: p in expected.universe for p in paths}


def check_select_targets(display: Display, scene: InteractionScene) -> None:
    """ICON-18, ICON-20, ICON-21: each element's target at the prim level and every kind, and the fixture's cases."""
    stage = display.stage
    for expected in _generations(display, scene):
        paths = sorted(expected.elements | {path for path, _ in scene.kind_targets})
        entities = [entity(stage, path) for path in paths]
        for level in oracle.levels():
            targets = display.select_targets(entities, level)
            assert targets == [oracle.kind_target(stage, oracle.floor(stage, p), level) for p in paths], level
        for (path, level), target in scene.kind_targets.items():
            assert display.select_targets([entity(stage, path)], level) == [target], (path, level)


def check_absent_floor(display: Display, scene: InteractionScene) -> None:
    """ICON-21: at a kind level, an entity whose floor is absent from the live stage targets its floor."""
    if scene.absent_floor is None:
        raise NotApplicableError
    removed, path, level = scene.absent_floor
    display.publish(scene.times[0])
    stage = display.stage
    source = entity(stage, path)
    floor = oracle.floor(stage, path)
    stage.RemovePrim(removed)  # the live stage now differs from the published generation
    assert not stage.GetPrimAtPath(floor)
    assert display.select_targets([source], level) == [floor]


def check_inspection_is_read_only(display: Display, scene: InteractionScene) -> None:
    """ICON-06: kind-level selection leaves the stage's layers, load set, and population mask unchanged."""
    stage = display.stage

    def state() -> tuple[Any, ...]:
        layers = sorted((layer.identifier, layer.ExportToString(), layer.dirty) for layer in stage.GetUsedLayers())
        return layers, sorted(map(str, stage.GetLoadSet())), stage.GetPopulationMask()

    for expected in _generations(display, scene):
        before = state()
        entities = [entity(stage, path) for path in sorted(expected.elements)]
        for level in oracle.levels()[1:]:
            display.select_targets(entities, level)
            for obj in display.managed_objects():
                obj.select_set(bool(display.coverage(obj)), view_layer=display.view_layer)
            display.selection_from_blender(display.read_blender_selection(), level)
        assert state() == before, expected.time


def check_highlight_targets(display: Display, scene: InteractionScene) -> None:
    """ICON-10, ICON-22, ICON-23, INSP-02: highlighting covers exactly the expanded entities' viewport elements."""
    stage = display.stage
    for expected in _generations(display, scene):
        for target in [*oracle.all_paths(stage), *scene.probes]:
            _assert_covers(display, [target], expected.beneath(target))
        for level in oracle.levels():
            targets = sorted({oracle.kind_target(stage, f, level) for f in expected.floors.values()})
            _assert_covers(display, targets, frozenset().union(*map(expected.beneath, targets)))


def _assert_covers(display: Display, targets: list[str], elements: frozenset[str]) -> None:
    covered = display.covered(display.highlight_targets(targets))
    assert all(c <= elements for c in covered), (targets, covered)  # none outside
    assert frozenset().union(*covered) == elements, targets  # none missing


def check_apply_selection(display: Display, scene: InteractionScene) -> None:
    """ICON-27, ICON-28, ICON-29: mirroring a source selection into Blender's selection and active object, exactly."""
    import bpy

    view_layer = display.view_layer
    unmanaged = [bpy.data.objects.new(name, None) for name in ("UnmanagedSelected", "UnmanagedUnselected")]
    for obj in unmanaged:
        _scene_collection().objects.link(obj)
    unmanaged[0].select_set(True, view_layer=view_layer)
    stage = display.stage
    for expected in _generations(display, scene):
        for level in oracle.levels():
            targets = [oracle.kind_target(stage, f, level) for f in sorted(set(expected.floors.values()))]
            # Each target alone and active, all of them with the first active, and an empty selection.
            cases = [([t], t) for t in targets] + [(targets, targets[0] if targets else None), ([], None)]
            for selected, active in cases:
                display.apply_selection(
                    display.highlight_targets(selected), display.highlight_targets([active] if active else [])
                )
                expanded = frozenset().union(*map(expected.beneath, selected))
                shown: frozenset[str] = frozenset()
                for obj in display.managed_objects():
                    coverage = display.coverage(obj)
                    if coverage and coverage <= expanded:
                        assert obj.select_get(view_layer=view_layer), (selected, obj.name)
                    if not coverage & expanded:
                        assert not obj.select_get(view_layer=view_layer), (selected, obj.name)
                    if obj.select_get(view_layer=view_layer):
                        shown |= coverage
                # Partial coverage (M4, D3, for review): none arises, so the selected objects show exactly the
                # selection's viewport elements.
                assert shown == expanded, (selected, shown ^ expanded)
                # Read back, the mirrored selection gives the targets of its elements (ICON-30), which for a target
                # with a nested model of its level include that model's.
                read = display.selection_from_blender(display.read_blender_selection(), level)
                own = {e: oracle.kind_target(stage, f, level) for e, f in expected.floors.items()}
                assert sorted(read.targets) == sorted({own[e] for e in expanded}), (level, selected, read)
                if active is not None:
                    showing = [o for o in display.managed_objects() if display.coverage(o) & expected.beneath(active)]
                    assert view_layer.objects.active == (showing[0] if len(showing) == 1 else None), active
                    assert all(o.select_get(view_layer=view_layer) for o in showing), active
                    if len(showing) == 1:  # the target of an element the active object shows
                        assert read.active in {own[e] for e in display.coverage(showing[0])}, (active, read)
                    else:
                        assert read.active is None, (active, read)
                assert [o.select_get(view_layer=view_layer) for o in unmanaged] == [True, False], selected


def check_selection_from_blender(display: Display, scene: InteractionScene) -> None:
    """ICON-30: Blender's selection, read back, gives the targets of its objects' entities at each level."""
    view_layer = display.view_layer
    stage = display.stage
    for expected in _generations(display, scene):
        shown = [obj for obj in display.managed_objects() if display.coverage(obj)]
        cases = [[obj] for obj in shown] + [shown]
        for level in oracle.levels():
            for chosen in cases:
                for obj in display.managed_objects():
                    obj.select_set(obj in chosen, view_layer=view_layer)
                view_layer.objects.active = chosen[0] if chosen else None
                selection = display.selection_from_blender(display.read_blender_selection(), level)
                targets = {e: oracle.kind_target(stage, f, level) for e, f in expected.floors.items()}
                wanted = {targets[e] for obj in chosen for e in display.coverage(obj)}
                assert len(selection.targets) == len(wanted), (level, selection)
                assert set(selection.targets) == wanted, (level, selection)
                active = display.coverage(chosen[0])
                if len(active) == 1:
                    assert selection.active == targets[next(iter(active))], (level, selection)


def _scene_collection() -> bpy.types.Collection:
    import bpy

    scene: Any = bpy.context.scene  # never None in a running Blender
    return scene.collection


CHECKS: dict[str, Callable[[Display, InteractionScene], None]] = {
    check.__name__.removeprefix("check_"): check
    for check in (
        check_picks,
        check_picks_ignore_names_and_parenting,
        check_displayed,
        check_select_targets,
        check_absent_floor,
        check_inspection_is_read_only,
        check_highlight_targets,
        check_apply_selection,
        check_selection_from_blender,
    )
}
