"""The interaction fixtures produce what they claim, and support/interaction_oracle.py derives the same from USD."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Kind, Usd

from fixtures import interaction
from support import interaction_oracle as oracle

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path

    from fixtures.interaction import InteractionScene

GENERATORS: dict[str, Callable[[Path], AbstractContextManager[InteractionScene]]] = {
    "F-KIND-HIERARCHY": interaction.kind_hierarchy,
    "F-NESTED-SELECTION": interaction.nested_selection,
    "F-UNIVERSE-MEMBERSHIP": interaction.universe_membership,
}

pytestmark = pytest.mark.parametrize("fixture_id", list(GENERATORS))


def test_oracle_finds_the_display_elements_and_universe(fixture_id: str, tmp_path: Path) -> None:
    with GENERATORS[fixture_id](tmp_path) as scene:
        for time in scene.times:
            expected = oracle.generation(scene.stage, time)
            assert expected.elements == scene.elements[time]
            assert expected.universe == scene.universe[time]
            assert expected.floors == {e: scene.floors.get(e, e) for e in scene.elements[time]}


def test_oracle_finds_the_kind_targets(fixture_id: str, tmp_path: Path) -> None:
    with GENERATORS[fixture_id](tmp_path) as scene:
        for (entity, level), target in scene.kind_targets.items():
            assert oracle.kind_target(scene.stage, oracle.floor(scene.stage, entity), level) == target


def test_excluded_prims_are_composed_and_outside_every_universe(fixture_id: str, tmp_path: Path) -> None:
    with GENERATORS[fixture_id](tmp_path) as scene:
        composed = set(oracle.all_paths(scene.stage))
        for path in scene.excluded:
            assert path in composed
            assert all(path not in members for members in scene.universe.values())
        assert not composed & set(scene.probes)


def test_kinds_outside_a_valid_model_hierarchy(fixture_id: str, tmp_path: Path) -> None:
    with GENERATORS[fixture_id](tmp_path) as scene:
        if not scene.outside_model_hierarchy:
            pytest.skip("no case outside a valid model hierarchy")
        for path in scene.outside_model_hierarchy:
            prim = scene.stage.GetPrimAtPath(path)
            assert Kind.Registry.IsA(Usd.ModelAPI(prim).GetKind(), Kind.Tokens.model), path
            assert not prim.IsModel(), path


def test_absent_floor_is_a_displayed_floor(fixture_id: str, tmp_path: Path) -> None:
    with GENERATORS[fixture_id](tmp_path) as scene:
        if scene.absent_floor is None:
            pytest.skip("no absent-floor case")
        removed, entity, _level = scene.absent_floor
        floor = scene.floors.get(entity, entity)
        assert entity in scene.elements[scene.times[0]]
        assert floor == removed or floor.startswith(removed + "/")
