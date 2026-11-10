"""The outline drawn around a zone: a rounded convex hull of its nodes' rectangles, wider around nested zones.

Each node's rectangle is padded, the hull of their corners is taken, and the hull is rounded by growing it with a
circle. As in Geometry Nodes, a zone's sides cut through the middle of its begin and end: it holds only the begin's
right half and the end's left half. A zone's hull takes each zone nested in it grown by a margin, and that zone's
begin and end whole, so a nested zone lies inside its parent. Coordinates are the node editor's view space. Nothing
here imports bpy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import zone_model

Point = tuple[float, float]

ARC_STEPS = 6  # points per quarter circle where a hull is rounded


@dataclass(frozen=True, slots=True)
class Rect:
    """A node's bounds in view space."""

    left: float
    bottom: float
    right: float
    top: float


def _corners(rect: Rect, pad: float, left: float | None = None, right: float | None = None) -> list[Point]:
    """A rectangle's padded corners; `left` or `right` replaces that side, unpadded."""
    x0 = rect.left - pad if left is None else left
    x1 = rect.right + pad if right is None else right
    return [(x0, rect.bottom - pad), (x1, rect.bottom - pad), (x1, rect.top + pad), (x0, rect.top + pad)]


def grown(polygon: list[Point], radius: float) -> list[Point]:
    """A convex polygon grown by `radius` (its Minkowski sum with a circle), as the hull of arcs at its vertices."""
    if radius <= 0:
        return polygon
    points: list[Point] = []
    steps = ARC_STEPS * 4
    for x, y in polygon:
        points += [
            (x + radius * math.cos(2 * math.pi * i / steps), y + radius * math.sin(2 * math.pi * i / steps))
            for i in range(steps)
        ]
    return convex_hull(points)


def convex_hull(points: list[Point]) -> list[Point]:
    """The convex hull, counter-clockwise, by Andrew's monotone chain."""
    unique = sorted(set(points))
    if len(unique) < 3:
        return unique

    def cross(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    for p in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Point] = []
    for p in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def zone_core(
    zone: zone_model.Zone,
    layout: zone_model.ZoneLayout,
    rects: dict[int, Rect],
    child_cores: list[list[Point]],
    pad: float,
    nest_pad: float,
    radius: float,
) -> list[Point]:
    """A zone's core, or nothing when none of its nodes has a rectangle.

    The core is the hull of its nodes' corners, padded by `pad - radius`, and of its nested zones' cores grown by
    `nest_pad`. The zone's hull is its core grown by `radius`, so only hull vertices are rounded. The begin's left
    side and the end's right side are moved to their middles, less `radius`, so the hull's sides cross them there.
    """
    inner_pad = max(pad - radius, 0.0)
    points: list[Point] = []
    for uid in core_nodes(zone, layout):
        rect = rects.get(uid)
        if rect is None:
            continue
        middle = (rect.left + rect.right) / 2
        if uid == zone.begin_uid:
            points += _corners(rect, inner_pad, left=middle + radius)
        elif uid == zone.end_uid:
            points += _corners(rect, inner_pad, right=middle - radius)
        else:
            points += _corners(rect, inner_pad)
    for core in child_cores:
        points += grown(core, nest_pad)
    return convex_hull(points) if points else []


def core_nodes(zone: zone_model.Zone, layout: zone_model.ZoneLayout) -> list[int]:
    """The nodes whose rectangles a zone's core takes directly.

    They are its begin and end, the nodes it holds that no zone nested in it holds, and the begin and end of each
    zone nested directly in it, whose outer halves lie outside that zone's own hull.
    """
    own = [
        uid
        for uid in (zone.begin_uid, zone.end_uid, *zone.body_node_uids)
        if layout.innermost_zone_by_node_uid.get(uid) is zone
    ]
    return own + [uid for child in zone.children for uid in (child.begin_uid, child.end_uid)]


def zone_hulls(
    layout: zone_model.ZoneLayout, rects: dict[int, Rect], pad: float, nest_pad: float, radius: float
) -> dict[int, list[Point]]:
    """Each zone's hull, by its begin's uid; a zone whose nodes have no rectangles has none."""
    cores: dict[int, list[Point]] = {}
    for zone in sorted(layout.zones, key=lambda z: -z.depth):  # nested zones first
        children = [cores[child.begin_uid] for child in zone.children if cores.get(child.begin_uid)]
        cores[zone.begin_uid] = zone_core(zone, layout, rects, children, pad, nest_pad, radius)
    return {begin: grown(core, radius) for begin, core in cores.items() if core}


def fan_triangles(hull: list[Point]) -> list[tuple[int, int, int]]:
    """Triangles that fill a convex polygon, as index triples."""
    return [(0, i, i + 1) for i in range(1, len(hull) - 1)]
