"""Headless checks of the zone rules and the hull, and timings at scale. Needs no bpy.

Run with ``uv run python tools/feasibility/node_zones/bench.py``.
"""

from __future__ import annotations

import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import zone_hull  # noqa: E402 (found through the path inserted above when run as a script)
import zone_model  # noqa: E402
from zone_model import GraphLink, GraphNode, ZoneRole  # noqa: E402

PLAIN, BEGIN, END, PINNED = ZoneRole.PLAIN, ZoneRole.BEGIN, ZoneRole.END, ZoneRole.PINNED


def _links(*pairs: tuple[int, int]) -> list[GraphLink]:
    return [GraphLink(a, b) for a, b in pairs]


def check_rules() -> None:
    # 1 input (pinned) -> 2 begin A -> 3 -> 4 begin B -> 5 -> 6 end B -> 7 -> 8 end A -> 9 output (pinned)
    # 10 feeds only 5 (joins B by rule 2); 11 consumes 3 and feeds 9 (leaves A: invalid); 12 begin with no end;
    # 13 feeds 5 and 9 (stays outside: not all its consumers are inside).
    nodes = [
        GraphNode(1, PINNED),
        GraphNode(2, BEGIN, "A", 8),
        GraphNode(3),
        GraphNode(4, BEGIN, "B", 6),
        GraphNode(5),
        GraphNode(6, END, "B"),
        GraphNode(7),
        GraphNode(8, END, "A"),
        GraphNode(9, PINNED),
        GraphNode(10),
        GraphNode(11),
        GraphNode(12, BEGIN, "A", 0),
        GraphNode(13),
    ]
    links = _links((1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 9), (10, 5), (3, 11), (11, 9))
    links += _links((13, 5), (13, 9))
    result = zone_model.layout(nodes, links)
    outer, inner = result.zones
    assert (outer.begin, inner.begin) == (2, 4), result.zones
    assert inner.parent is outer and inner.depth == 1
    assert inner.body == {5, 10}, inner.body
    assert outer.body == {3, 4, 5, 6, 7, 10, 11}, outer.body
    assert result.zone_of[5] is inner and result.zone_of[7] is outer and 13 not in result.zone_of
    assert result.invalid_links == {10}, result.invalid_links  # 11 -> 9 leaves zone A
    assert result.problems == ["begin 12 (A) has no end"], result.problems

    # A link from inside back into the zone's begin, and an end's output used inside its own zone.
    nodes = [GraphNode(1, BEGIN, "A", 3), GraphNode(2), GraphNode(3, END, "A"), GraphNode(4)]
    result = zone_model.layout(nodes, _links((1, 2), (2, 3), (2, 1)))
    assert result.invalid_links == {2}, result.invalid_links
    # Overlapping zones: B's begin is in A, B's end isn't.
    nodes = [GraphNode(1, BEGIN, "A", 3), GraphNode(2, BEGIN, "B", 4), GraphNode(3, END, "A"), GraphNode(4, END, "B")]
    result = zone_model.layout(nodes, _links((1, 2), (2, 3), (3, 4)))
    assert any("overlaps" in p for p in result.problems), result.problems
    print("zone rules: ok")


def check_repair() -> None:
    # Begin 1 pairs with 2. Duplicating both makes 3 (from 1, partner 2) and 4 (from 2).
    assert zone_model.repaired_partners([(1, 2, 0), (2, 0, 0), (3, 2, 1), (4, 0, 2)]) == {3: 4}
    # Duplicating only the begin: the copy is unpaired, the original keeps its end.
    assert zone_model.repaired_partners([(1, 2, 0), (2, 0, 0), (3, 2, 1)]) == {3: 0}
    # Duplicating only the end: nothing changes; the copy is an end with no begin.
    assert zone_model.repaired_partners([(1, 2, 0), (2, 0, 0), (4, 0, 2)]) == {}
    # Deleting the end unpairs the begin.
    assert zone_model.repaired_partners([(1, 2, 0)]) == {1: 0}
    print("pair repair: ok")


def check_orphans() -> None:
    # Zones 1-2 and 3-4, and an unpaired end 5.
    nodes = [(1, 2), (2, 0), (3, 4), (4, 0), (5, 0)]
    assert zone_model.orphaned_partners([(2, 0)], [n for n in nodes if n[0] != 2]) == {1}  # end deleted: its begin
    assert zone_model.orphaned_partners([(3, 4)], [n for n in nodes if n[0] != 3]) == {4}  # begin deleted: its end
    assert zone_model.orphaned_partners([(1, 2), (2, 0)], [n for n in nodes if n[0] > 2]) == set()  # both deleted
    assert zone_model.orphaned_partners([(5, 0)], nodes[:4]) == set()  # an unpaired end takes nothing
    print("orphans: ok")


def check_hull() -> None:
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.5, 0.5), (0.2, 0.8)]
    assert zone_hull.convex_hull(square) == [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    nodes = [GraphNode(1, BEGIN, "A", 3), GraphNode(2), GraphNode(3, END, "A")]
    result = zone_model.layout(nodes, _links((1, 2), (2, 3)))
    rects = {
        1: zone_hull.Rect(0, 0, 100, 50),
        2: zone_hull.Rect(200, 100, 300, 150),
        3: zone_hull.Rect(400, 0, 500, 50),
    }
    hull = zone_hull.zone_hulls(result, rects, pad=10, nest_pad=10, radius=5)[1]
    # The sides cut through the middles of the begin (0-100) and the end (400-500); top and bottom are padded.
    assert _bounds(hull) == (50, 450, -10, 160), _bounds(hull)

    # Zone 2-4 nested in zone 1-5: the outer hull holds the inner zone's begin and end whole, with a margin.
    nodes = [GraphNode(1, BEGIN, "A", 5), GraphNode(2, BEGIN, "B", 4), GraphNode(3), GraphNode(4, END, "B")]
    nodes.append(GraphNode(5, END, "A"))
    result = zone_model.layout(nodes, _links((1, 2), (2, 3), (3, 4), (4, 5)))
    rects = {uid: zone_hull.Rect(uid * 200, 0, uid * 200 + 100, 50) for uid in range(1, 6)}
    hulls = zone_hull.zone_hulls(result, rects, pad=10, nest_pad=10, radius=5)
    assert _bounds(hulls[2]) == (450, 850, -10, 60), _bounds(hulls[2])
    assert _bounds(hulls[1]) == (250, 1050, -20, 70), _bounds(hulls[1])  # the inner begin's left side is 400
    print("hull: ok")


def _bounds(hull: list[zone_hull.Point]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in hull], [p[1] for p in hull]
    return round(min(xs), 6), round(max(xs), 6), round(min(ys), 6), round(max(ys), 6)


def _synthetic(zones: int, per_zone: int, depth: int) -> tuple[list[GraphNode], list[GraphLink]]:
    """Chains of zones, `depth` deep, each holding a chain of `per_zone` nodes and a value node feeding it."""
    rng = random.Random(1)
    nodes: list[GraphNode] = []
    links: list[GraphLink] = []
    uid = 0

    def new(role: ZoneRole = PLAIN, kind: str = "", partner: int = 0) -> int:
        nonlocal uid
        uid += 1
        nodes.append(GraphNode(uid, role, kind, partner))
        return uid

    previous = new(PINNED)
    for _ in range(zones // depth):
        begins: list[int] = []
        for _ in range(depth):  # open `depth` nested zones; ends get uids after the body is made
            begin = new(BEGIN, "A")
            links.append(GraphLink(previous, begin))
            begins.append(begin)
            previous = begin
        for _ in range(per_zone):
            node = new()
            links.append(GraphLink(previous, node))
            if rng.random() < 0.2:
                links.append(GraphLink(new(), node))  # a value used only inside
            previous = node
        for begin in reversed(begins):
            end = new(END, "A")
            nodes[begin - 1] = GraphNode(begin, BEGIN, "A", end)
            links.append(GraphLink(previous, end))
            previous = end
    links.append(GraphLink(previous, new(PINNED)))
    return nodes, links


def bench() -> None:
    print(f"{'nodes':>7} {'zones':>6} {'depth':>6} {'layout ms':>10} {'hulls ms':>9}")
    for zones, per_zone, depth in ((10, 10, 1), (50, 20, 2), (100, 50, 3), (500, 20, 5)):
        nodes, links = _synthetic(zones, per_zone, depth)
        start = time.perf_counter()
        result = zone_model.layout(nodes, links)
        layout_ms = (time.perf_counter() - start) * 1000
        assert not result.problems and not result.invalid_links, result.problems[:3]
        rects = {n.uid: zone_hull.Rect(n.uid * 200.0, 0.0, n.uid * 200.0 + 140, 100.0) for n in nodes}
        start = time.perf_counter()
        zone_hull.zone_hulls(result, rects, pad=18, nest_pad=14, radius=14)
        hull_ms = (time.perf_counter() - start) * 1000
        print(f"{len(nodes):>7} {len(result.zones):>6} {depth:>6} {layout_ms:>10.1f} {hull_ms:>9.1f}")


if __name__ == "__main__":
    check_rules()
    check_repair()
    check_orphans()
    check_hull()
    bench()
