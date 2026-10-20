"""Source-entity identifiers against M2's interaction fixtures and oracle (interaction-contract.md).

Every entity the oracle names, displayed elements and their floors, universe members, and
kind-level targets, survives as an identifier and resolves to the prim the oracle meant. Inside
instance contents that is an instance proxy, and copies of one prototype prim through different
instances have different identifiers.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

import pytest
from pxr import Sdf

from fixtures import interaction
from proscenium.core.source_entities import entity_path, identifier
from support import interaction_oracle

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from contextlib import AbstractContextManager
    from pathlib import Path

    from fixtures.interaction import InteractionScene

FIXTURES: dict[str, Callable[[Path], AbstractContextManager[InteractionScene]]] = {
    "F-KIND-HIERARCHY": interaction.kind_hierarchy,
    "F-NESTED-SELECTION": interaction.nested_selection,
    "F-UNIVERSE-MEMBERSHIP": interaction.universe_membership,
}


@pytest.fixture(params=list(FIXTURES))
def scene(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[InteractionScene]:
    with FIXTURES[request.param](tmp_path) as built:
        yield built


def _named(scene: InteractionScene) -> set[str]:
    """Every entity the oracle names on the fixture's live stage, at each of its times and levels."""
    named: set[str] = set()
    for time in scene.times:
        generation = interaction_oracle.generation(scene.stage, time)
        named |= generation.elements | generation.universe | set(generation.floors.values())
        for floor in generation.floors.values():
            named |= {
                interaction_oracle.kind_target(scene.stage, floor, level) for level in interaction_oracle.levels()
            }
    return named


def test_every_named_entity_round_trips(scene: InteractionScene) -> None:
    for path in _named(scene):
        assert identifier(Sdf.Path(path)) == path
        assert entity_path(path) == Sdf.Path(path)


def test_identifiers_resolve_to_the_oracles_prims(scene: InteractionScene) -> None:
    # Inside instance contents, an element is an instance proxy; its floor is the instance it's in.
    for time in scene.times:
        generation = interaction_oracle.generation(scene.stage, time)
        for element, floor in generation.floors.items():
            prim = scene.stage.GetPrimAtPath(entity_path(element))
            assert prim, element
            assert prim.IsInstanceProxy() == (floor != element)


def test_copies_through_different_instances_have_their_own_identifiers(tmp_path: Path) -> None:
    # F-NESTED-SELECTION shows a prototype's prims through several instances.
    with interaction.nested_selection(tmp_path) as scene:
        by_prototype: dict[str, set[str]] = defaultdict(set)
        for time in scene.times:
            for element in interaction_oracle.generation(scene.stage, time).elements:
                prim = scene.stage.GetPrimAtPath(entity_path(element))
                if prim.IsInstanceProxy():
                    by_prototype[str(prim.GetPrimInPrototype().GetPath())].add(identifier(prim.GetPath()))
        shared = [ids for ids in by_prototype.values() if len(ids) > 1]
        assert shared, "the fixture shows a prototype prim through more than one instance"


@pytest.mark.parametrize(
    "text",
    ["", "World", "/", "/World.size", "/World{v=a}", "/World{v=a}Inner", "/World/", "/World//A", "not a path", 7],
)
def test_what_isnt_an_entity_is_rejected(text: object) -> None:
    with pytest.raises(ValueError):  # each case fails a different check
        entity_path(text)  # ty: ignore[invalid-argument-type]


def test_a_path_that_cant_name_an_entity_has_no_identifier() -> None:
    for path in (Sdf.Path("/"), Sdf.Path("/World.size"), Sdf.Path("World")):
        with pytest.raises(ValueError, match="not an absolute prim path"):
            identifier(path)
