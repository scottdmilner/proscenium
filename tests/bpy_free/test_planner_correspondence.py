"""The planner's correspondence, from display elements as Python gives them (DECISIONS.md "Persisted correspondence").

Elements here come from a plan's correspondence and its viewport participation, as a held plan gives them. Expected
values come from the interaction fixtures and USD's own APIs (support/interaction_oracle.py), and from
F-POINT-INSTANCERS' construction. The display's correspondence, built from the manifest and Blender data, is checked
in tests/blender.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Sdf, Usd

from fixtures import evaluation, interaction
from proscenium_sync import planner
from support import interaction_oracle

from .plan_checks import plan_at

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path

IDENTITY = Gf.Matrix4d(1.0)
SCENES: dict[str, Callable[[Path], AbstractContextManager[interaction.InteractionScene]]] = {
    "F-KIND-HIERARCHY": interaction.kind_hierarchy,
    "F-NESTED-SELECTION": interaction.nested_selection,
    "F-UNIVERSE-MEMBERSHIP": interaction.universe_membership,
}


def _correspondence(stage: Usd.Stage, plan: planner.Plan, *, with_contexts: bool) -> planner.Correspondence:
    """The plan's copies as display elements, with its contexts or with none, so the live stage gives them."""
    entries = plan.correspondence
    return planner.Correspondence(
        stage,
        [e.source_path for e in entries],
        [e.instance_context if with_contexts else None for e in entries],
        [bool(v) for v in memoryview(plan.copy_visible_in_viewport).tolist()],
    )


@pytest.mark.parametrize("fixture", SCENES)
def test_correspondence_answers_as_the_fixture_expects(tmp_path: Path, fixture: str) -> None:
    # ICON-11 to ICON-15, ICON-22, ICON-23 at the correspondence layer: at each of the fixture's time codes, displayed
    # is true exactly for the universe, its probes and every other composed prim included, and highlight_targets of
    # each prim covers exactly the viewport elements at or beneath it in the universe.
    with SCENES[fixture](tmp_path) as scene:
        for time in scene.times:
            plan = plan_at(scene.stage, time)
            correspondence = _correspondence(scene.stage, plan, with_contexts=True)
            paths = [*interaction_oracle.all_paths(scene.stage), *scene.probes]
            displayed = memoryview(correspondence.displayed(paths)).tolist()
            assert {p for p, shown in zip(paths, displayed, strict=True) if shown} == scene.universe[time], time
            sources = [e.source_path for e in plan.correspondence]
            viewport = memoryview(plan.copy_visible_in_viewport).tolist()
            assert {s for s, shown in zip(sources, viewport, strict=True) if shown} == scene.elements[time], time
            for target in scene.universe[time]:
                covered = {sources[i] for i in memoryview(correspondence.highlight_targets([target])).tolist()}
                root = Sdf.Path(target)
                expected = {e for e in scene.elements[time] if Sdf.Path(scene.floors.get(e, e)).HasPrefix(root)}
                assert covered == expected, (time, target)


@pytest.mark.parametrize("fixture", ["F-NESTED-SELECTION", "F-KIND-HIERARCHY"])
def test_contexts_on_the_live_stage_are_the_plans(tmp_path: Path, fixture: str) -> None:
    # ICON-35's instance contexts: with none given, as after reopening, each element's instance context and floor from
    # its source path on the live stage are the plan's, inside nested native instances too.
    with SCENES[fixture](tmp_path) as scene:
        plan = plan_at(scene.stage, scene.times[0])
        derived = _correspondence(scene.stage, plan, with_contexts=False)
        for index, entry in enumerate(plan.correspondence):
            entity = derived.resolve_pick(index, IDENTITY)
            assert entity is not None
            assert (entity.source_path, entity.instance_context) == (entry.source_path, entry.instance_context)
            assert entity.floor == scene.floors.get(entry.source_path, entry.source_path)


def test_point_instance_contexts_on_the_live_stage(tmp_path: Path) -> None:
    # ICON-35's instance contexts for point-instance paths: the instancer and the point, after the native-instance
    # roots enclosing the instancer (Kits), and before those inside the prototype (Pebble), as F-POINT-INSTANCERS
    # gives them.
    with evaluation.point_instancers(tmp_path) as scene:
        plan = plan_at(scene.stage, 0.0)
        derived = _correspondence(scene.stage, plan, with_contexts=False)
        for index, entry in enumerate(plan.correspondence):
            entity = derived.resolve_pick(index, IDENTITY)
            assert entity is not None
            assert entity.instance_context == scene.instance_context[entry.source_path], entry.source_path
            assert entity.floor == scene.floors[entry.source_path], entry.source_path


def test_a_pick_past_the_elements_names_nothing(tmp_path: Path) -> None:
    with interaction.kind_hierarchy(tmp_path) as scene:
        plan = plan_at(scene.stage, scene.times[0])
        correspondence = _correspondence(scene.stage, plan, with_contexts=True)
        assert correspondence.element_count == len(plan.correspondence)
        assert correspondence.resolve_pick(correspondence.element_count, IDENTITY) is None


def test_render_only_elements_are_not_browsable(tmp_path: Path) -> None:
    # ICON-12: elements outside the viewport make nothing displayed, and no highlight covers them.
    with interaction.kind_hierarchy(tmp_path) as scene:
        plan = plan_at(scene.stage, scene.times[0])
        entries = plan.correspondence
        hidden = planner.Correspondence(
            scene.stage, [e.source_path for e in entries], [e.instance_context for e in entries], [False] * len(entries)
        )
        assert not any(memoryview(hidden.displayed(sorted(scene.universe[scene.times[0]]))).tolist())
        assert not memoryview(hidden.highlight_targets(["/"])).tolist()


def test_without_a_live_stage_the_source_is_unavailable(tmp_path: Path) -> None:
    # ICON-08 at the correspondence layer: once the live stage expires, each function raises SourceUnavailableError,
    # as does building a correspondence without one.
    with interaction.kind_hierarchy(tmp_path) as scene:
        plan = plan_at(scene.stage, scene.times[0])
        stage = Usd.Stage.Open(str(scene.root_layer_path))
        correspondence = _correspondence(stage, plan, with_contexts=False)
        del stage
        calls = [
            lambda: correspondence.resolve_pick(0, IDENTITY),
            lambda: correspondence.displayed(["/"]),
            lambda: correspondence.highlight_targets(["/"]),
            lambda: planner.Correspondence(None, [], [], []),
        ]
        for call in calls:
            with pytest.raises(planner.SourceUnavailableError):
                call()


def test_parallel_inputs_must_agree_in_length(tmp_path: Path) -> None:
    with interaction.kind_hierarchy(tmp_path) as scene, pytest.raises(ValueError, match="differ in length"):
        planner.Correspondence(scene.stage, ["/A"], [None], [])
