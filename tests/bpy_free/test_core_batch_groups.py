"""Batch groups in the core (M6 plan, C8): the copies a batch shows as instances of one prototype, as the bridge groups.

Copies share a group when they copy one mesh to the same destinations; copies at equal float32 world transforms go to
separate groups, each a repeat, since a pick names an instance by its transform; placeholders and markers stay single;
a group under the minimum stays single copies. Expected groups come from the fixtures and UsdGeom: on
F-POINT-INSTANCERS, copies of one USD prim, the instance proxies' prims in their prototype, Hydra draws as one mesh.
"""

from __future__ import annotations

from array import array
from collections import Counter
from typing import TYPE_CHECKING

import pytest

from fixtures import evaluation

from .plan_checks import plan_at

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from proscenium.core import _core


@pytest.fixture
def points(tmp_path: Path) -> Iterator[evaluation.PointInstancerScene]:
    with evaluation.point_instancers(tmp_path) as scene:
        yield scene


def _groups(plan: _core.Plan, minimum: int) -> tuple[list[tuple[int, list[str]]], list[str]]:
    """The plan's groups as (repeat, member sources), and its single copies' sources."""
    sources = [c.source_path for c in plan.correspondence]
    groups, single = plan.batch_groups(minimum)
    return (
        [(g.coincident_copy_index, [sources[i] for i in memoryview(g.copy_indices).tolist()]) for g in groups],
        [sources[i] for i in memoryview(single).tolist()],
    )


def _expected(scene: evaluation.PointInstancerScene, minimum: int) -> tuple[list[tuple[int, list[str]]], list[str]]:
    """The groups the fixture gives, in copy order (by source), by the mesh prim each copy draws and its visibility."""
    stage = scene.stage
    grouped: dict[tuple[str, bool, int], list[str]] = {}
    repeats: Counter[tuple[str, bool, tuple[float, ...]]] = Counter()
    for path in sorted(scene.world_matrices_by_source):
        prim = stage.GetPrimAtPath(scene.sources[path])
        drawn = str(prim.GetPrimInPrototype().GetPath() if prim.IsInstanceProxy() else prim.GetPath())
        visible = path not in scene.invisible
        world = scene.world_matrices_by_source[path]
        stored = tuple(array("f", [float(world[r, c]) for r in range(4) for c in range(4)]))  # as Blender stores it
        repeat = repeats[drawn, visible, stored]
        repeats[drawn, visible, stored] += 1
        grouped.setdefault((drawn, visible, repeat), []).append(path)
    groups = [(key[2], members) for key, members in grouped.items() if len(members) >= minimum]
    single = sorted(p for members in grouped.values() if len(members) < minimum for p in members)
    return groups, single


@pytest.mark.parametrize("minimum", [1, 2, 4, 5])
def test_copies_of_one_mesh_to_the_same_destinations_group(
    points: evaluation.PointInstancerScene, minimum: int
) -> None:
    # The four Pellets across Kits' two instances; Tagged's visible points but for the one at another's transform,
    # a repeat; the hidden points apart from the visible.
    assert _groups(plan_at(points.stage, 0.0), minimum) == _expected(points, minimum)


def test_a_coincident_copy_is_a_repeat(points: evaluation.PointInstancerScene) -> None:
    groups, _ = _groups(plan_at(points.stage, 0.0), 1)
    assert (1, ["/World/Tagged/__id_12/Rock"]) in groups  # where __id_10's copy is
    assert (0, ["/World/Tagged/__id_10/Rock", "/World/Tagged/__id_n3/Rock"]) in groups


def test_placeholders_and_markers_stay_single(tmp_path: Path) -> None:
    with evaluation.unsupported_content(tmp_path) as unsupported:
        groups, single = _groups(plan_at(unsupported.stage, 0.0), 1)
    grouped = {p for _, members in groups for p in members}
    assert set(unsupported.placeholders) <= set(single)
    assert grouped.isdisjoint(unsupported.placeholders)
