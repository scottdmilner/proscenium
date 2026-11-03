"""Correspondence in the baseline's plan (M04-prototypes plan, B2; M2's Q1): source entities, floors, and universe.

Each viewport display element of the plan must be one the M2 oracle expects, with the oracle's floor, and the
plan's universe must be the oracle's, at each time code a fixture publishes. Hydra flattens and regroups prims
(organizational prims, aggregated native instances), so this is what Q1 asks of the bridge's reverse mapping.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from fixtures import appearance, interaction
from support import interaction_oracle

from .harness import Runtime, run_isolated

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from pxr import Usd

BODY = Path(__file__).parent / "bodies/baseline.py"
# Each fixture with the time codes its generations are published at; the appearance fixtures are static.
FIXTURES: dict[str, tuple[Callable[[Path], Any], tuple[float, ...] | None]] = {
    "kind_hierarchy": (interaction.kind_hierarchy, None),
    "nested_selection": (interaction.nested_selection, None),
    "universe_membership": (interaction.universe_membership, None),
    "appearance_cases": (appearance.appearance_cases, (0.0,)),
    "nested_stress": (appearance.nested_stress, (0.0,)),
}


@pytest.fixture(params=list(FIXTURES))
def scene(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[tuple[Usd.Stage, Path, tuple[float, ...]]]:
    build, times = FIXTURES[request.param]
    with build(tmp_path) as built:
        yield built.stage, built.root, times or built.times


@pytest.fixture
def generations(
    scene: tuple[Usd.Stage, Path, tuple[float, ...]], wheel: Runtime, hydra_bridge: Path, tmp_path: Path
) -> dict[float, dict[str, Any]]:
    stage, root, times = scene
    # The body opens its own stage on the scene, with the caller's stage's unloaded payloads unloaded.
    unload = sorted(str(p) for p in set(stage.FindLoadable()) - set(stage.GetLoadSet()))
    result = run_isolated(
        wheel,
        BODY,
        "correspondence",
        tmp_path,
        module_dir=str(hydra_bridge),
        scene=str(root),
        times=list(times),
        unload=unload,
    )
    return {time: result[str(time)] for time in times}


def test_viewport_elements_and_floors(
    scene: tuple[Usd.Stage, Path, tuple[float, ...]], generations: dict[float, dict[str, Any]]
) -> None:
    stage = scene[0]
    for time, planned in generations.items():
        assert planned["errors"] == []
        expected = interaction_oracle.generation(stage, time)
        viewport = [o for o in planned["objects"] if o["viewport"]]
        assert {o["source"] for o in viewport} == expected.elements, time
        for obj in planned["objects"]:
            # Every object, shown in the viewport or not, names its entity's floor, from its instance context.
            assert obj["floor"] == interaction_oracle.floor(stage, obj["source"]), (time, obj)
            assert obj["floor"] == (obj["instance_context"] or [obj["source"]])[0], (time, obj)


def test_universe(scene: tuple[Usd.Stage, Path, tuple[float, ...]], generations: dict[float, dict[str, Any]]) -> None:
    stage = scene[0]
    for time, planned in generations.items():
        universe = planned["universe"]
        assert len(universe) == len(set(universe)), time
        assert set(universe) == interaction_oracle.generation(stage, time).universe, time
