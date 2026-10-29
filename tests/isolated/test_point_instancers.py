"""Point instancers planned for measurement (M04-prototypes plan, D6), in both representations.

The spec defers point instancers, so the bridge plans their instances only when asked (`build_plan`'s
`point_instancers`); otherwise each point instancer is one placeholder, as M1b decided. Each point's prototype
meshes are then one object or instance each, with the point's world transform as USD composes it, the mask's
visibility, the instancer's per-point and constant primvars, and USD's bound materials. Expected values come
from how the fixture is built (fixtures/appearance.py, point_instancers).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from fixtures import appearance

from .harness import Runtime, run_isolated

if TYPE_CHECKING:
    from collections.abc import Generator

    from fixtures.appearance import PointInstancerScene

BODY = Path(__file__).parent / "bodies/baseline.py"
POINT = "/__point_"  # what names a point in a copy's instance context
CLOSE = 1e-5  # float32 storage in Blender


@pytest.fixture
def scattered(tmp_path: Path) -> Generator[PointInstancerScene]:
    with appearance.point_instancers(tmp_path) as scene:
        yield scene


def _applied(scene: PointInstancerScene, runtime: Runtime, bridge: Path, tmp: Path, **kwargs: Any) -> dict[str, Any]:
    result = run_isolated(runtime, BODY, "apply_scene", tmp, module_dir=str(bridge), scene=str(scene.root), **kwargs)
    assert result["errors"] == []
    return result


def _point(obj: dict[str, Any]) -> int:
    (entry,) = [c for c in obj["instance_context"] if POINT in c]
    return int(entry.rsplit(POINT, 1)[1])


@pytest.mark.parametrize("representation", ["objects", "batched"])
def test_each_point_draws_its_prototype(
    scattered: PointInstancerScene, representation: str, wheel: Runtime, hydra_bridge: Path, tmp_path: Path
) -> None:
    result = _applied(scattered, wheel, hydra_bridge, tmp_path, representation=representation, point_instancers=True)
    objects = result["objects"]
    copies = {(o["source"], _point(o)): o for o in objects}
    assert len(copies) == len(objects)  # one per mesh and point
    assert copies.keys() == scattered.world.keys()  # nothing of the instancer itself, or the unused prototype
    for (mesh, point), obj in copies.items():
        # The instancer, then the point, then any native instance root inside the prototype.
        assert obj["instance_context"][:2] == [scattered.instancer, f"{scattered.instancer}{POINT}{point}"]
        expected = scattered.world[(mesh, point)]
        for world in (obj["plan_world"], obj["world"]):
            assert all(abs(world[r][c] - expected[r][c]) < CLOSE for r in range(4) for c in range(4)), (mesh, point)
        shown = point not in scattered.invisible
        assert (obj["viewport"], obj["render"]) == (shown, shown), (mesh, point)
        properties = obj["properties"]
        assert {name: properties.get(name) for name in ("heat", "groupId")} == pytest.approx(
            scattered.primvars[point]
        ), (mesh, point)
        assert obj["slots"] == [[scattered.materials[mesh]]], (mesh, point)
    if representation == "batched":
        # Copies of one mesh that display the same batch: the shown leaves and the rocks.
        instanced = {copy for copy, obj in copies.items() if obj["instance"]}
        leaves, rocks = (m for m in scattered.materials if m.endswith(("/Blade", "/Rock")))
        assert instanced == {(leaves, 0), (leaves, 2), (rocks, 1), (rocks, 5)}


def test_without_the_setting_the_instancer_is_a_placeholder(
    scattered: PointInstancerScene, wheel: Runtime, hydra_bridge: Path, tmp_path: Path
) -> None:
    objects = _applied(scattered, wheel, hydra_bridge, tmp_path)["objects"]
    assert [(o["source"], o["placeholder"]) for o in objects] == [(scattered.instancer, "PointInstancer")]
