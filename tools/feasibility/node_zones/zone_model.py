"""Zones in a node graph: which begin and end nodes pair, which nodes each zone holds, and which links cross out.

A zone is a begin node paired with an end node of the same kind. Only the begin stores the pairing (the end's
uid), as Blender's zone input nodes store their output's. A zone holds:
1. every node downstream of its begin, short of its end and of anything downstream of its end, and
2. every node whose consumers are all already in the zone or its end (a value used only inside), repeated until
   nothing more joins.
Interface nodes (`pinned`) never join a zone. A zone is nested in another when its begin and end both lie in that
zone; a node belongs to the innermost zone that holds it. A link is invalid when it leaves a zone other than
through the zone's end, or reaches into a zone's begin from inside that zone.

Copies are repaired with `repaired_partners`: a copied begin pairs with the copy of its end when both were copied
together, and with nothing otherwise. Deleting either half of a zone deletes the other, as in Geometry Nodes:
`orphaned_partners` names the nodes to remove. Nothing here imports bpy.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class ZoneRole(Enum):
    """What a node is to the zones."""

    PLAIN = "plain"
    BEGIN = "begin"
    END = "end"
    PINNED = "pinned"  # an interface node, kept out of every zone


@dataclass(frozen=True, slots=True)
class GraphNode:
    """One node, as the zones see it."""

    uid: int
    role: ZoneRole = ZoneRole.PLAIN
    zone_kind: str = ""  # begin and end nodes only
    partner_uid: int = 0  # a begin's end, or 0 when unpaired


@dataclass(frozen=True, slots=True)
class GraphLink:
    """One link, from a node's output to a node's input."""

    from_uid: int
    to_uid: int


@dataclass(slots=True)
class Zone:
    """A paired begin and end, the nodes between them, and where it nests."""

    kind: str
    begin_uid: int
    end_uid: int
    body_node_uids: frozenset[int] = (
        frozenset()
    )  # every node the zone holds, nested zones' included, its begin and end not
    parent: Zone | None = None
    children: list[Zone] = field(default_factory=list)

    @property
    def depth(self) -> int:
        """How many zones this one is nested in."""
        return 0 if self.parent is None else self.parent.depth + 1

    def holds(self, uid: int) -> bool:
        """Whether a node is in this zone, its begin and end included."""
        return uid in self.body_node_uids or uid in (self.begin_uid, self.end_uid)


@dataclass(slots=True)
class ZoneLayout:
    """The zones of one graph."""

    zones: list[Zone]  # outer zones before the zones nested in them
    innermost_zone_by_node_uid: dict[
        int, Zone
    ]  # each node in a zone (begin and end included) to the innermost zone holding it
    invalid_link_indices: set[int]  # positions in the link list
    problems: list[str]


def layout(nodes: list[GraphNode], links: list[GraphLink]) -> ZoneLayout:
    """The zones of a graph, where they nest, and the links that cross out of them."""
    by_uid = {node.uid: node for node in nodes}
    consumers: dict[int, list[int]] = {node.uid: [] for node in nodes}
    producers: dict[int, list[int]] = {node.uid: [] for node in nodes}
    for link in links:
        if link.from_uid in by_uid and link.to_uid in by_uid:
            consumers[link.from_uid].append(link.to_uid)
            producers[link.to_uid].append(link.from_uid)

    problems: list[str] = []
    zones = _paired_zones(by_uid, problems)
    for zone in zones:
        zone.body_node_uids = _body(zone, by_uid, consumers, producers)
    _nest(zones, problems)

    zone_of: dict[int, Zone] = {}
    for zone in sorted(zones, key=lambda z: z.depth):  # inner zones overwrite outer ones
        for uid in (*zone.body_node_uids, zone.begin_uid, zone.end_uid):
            zone_of[uid] = zone
    ordered = sorted(zones, key=lambda z: z.depth)
    return ZoneLayout(ordered, zone_of, _invalid_links(zones, links), problems)


def _paired_zones(by_uid: dict[int, GraphNode], problems: list[str]) -> list[Zone]:
    zones: list[Zone] = []
    claimed: dict[int, int] = {}  # end to the begin that paired with it
    for node in by_uid.values():
        if node.role is not ZoneRole.BEGIN:
            continue
        end = by_uid.get(node.partner_uid)
        if end is None or end.role is not ZoneRole.END or end.zone_kind != node.zone_kind:
            problems.append(f"begin {node.uid} ({node.zone_kind}) has no end")
            continue
        if end.uid in claimed:
            problems.append(f"end {end.uid} is claimed by begins {claimed[end.uid]} and {node.uid}")
            continue
        claimed[end.uid] = node.uid
        zones.append(Zone(node.zone_kind, node.uid, end.uid))
    problems.extend(
        f"end {node.uid} ({node.zone_kind}) has no begin"
        for node in by_uid.values()
        if node.role is ZoneRole.END and node.uid not in claimed
    )
    return zones


def _reach(start: int, edges: dict[int, list[int]], stop: set[int]) -> set[int]:
    """The nodes reached from `start` along `edges`, without passing through a node in `stop`."""
    seen: set[int] = set()
    queue = deque(edges[start])
    while queue:
        uid = queue.popleft()
        if uid in seen:
            continue
        seen.add(uid)
        if uid not in stop:
            queue.extend(edges[uid])
    return seen


def _body(
    zone: Zone, by_uid: dict[int, GraphNode], consumers: dict[int, list[int]], producers: dict[int, list[int]]
) -> frozenset[int]:
    after_end = _reach(zone.end_uid, consumers, set()) | {zone.end_uid}
    pinned = {uid for uid, node in by_uid.items() if node.role is ZoneRole.PINNED}
    body = _reach(zone.begin_uid, consumers, after_end | pinned) - after_end - pinned - {zone.begin_uid}

    # Rule 2: a node joins once every node it feeds is inside; each node that joins makes its producers candidates.
    inside = body | {zone.end_uid}
    queue = deque(inside)
    while queue:
        for producer in producers[queue.popleft()]:
            if producer in inside or producer in pinned or producer in after_end or producer == zone.begin_uid:
                continue
            if all(consumer in inside for consumer in consumers[producer]):
                inside.add(producer)
                queue.append(producer)
    return frozenset(inside - {zone.end_uid})


def _nest(zones: list[Zone], problems: list[str]) -> None:
    for inner in zones:
        holders: list[Zone] = []
        for zone in zones:
            if zone is inner:
                continue
            holds_begin, holds_end = inner.begin_uid in zone.body_node_uids, inner.end_uid in zone.body_node_uids
            if holds_begin != holds_end or (holds_begin and zone.begin_uid in inner.body_node_uids):
                problems.append(f"zone {inner.begin_uid}-{inner.end_uid} overlaps zone {zone.begin_uid}-{zone.end_uid}")
            elif holds_begin:
                holders.append(zone)
        if holders:  # the innermost holder; every other holder holds it too, so its body is the smallest
            inner.parent = min(holders, key=lambda zone: len(zone.body_node_uids))
            inner.parent.children.append(inner)


def _invalid_links(zones: list[Zone], links: list[GraphLink]) -> set[int]:
    invalid: set[int] = set()
    for position, link in enumerate(links):
        for zone in zones:
            if link.from_uid not in zone.body_node_uids:
                continue
            leaves = not zone.holds(link.to_uid)
            feeds_back = link.to_uid == zone.begin_uid
            if leaves or feeds_back:
                invalid.add(position)
                break
        else:
            for zone in zones:  # an end's output used inside its own zone
                if link.from_uid == zone.end_uid and link.to_uid in zone.body_node_uids:
                    invalid.add(position)
                    break
    return invalid


def repaired_partners(nodes: list[tuple[int, int, int]]) -> dict[int, int]:
    """The begins whose partner must change after a copy or a deletion, and their new partners (0: unpaired).

    `nodes` holds `(uid, partner, copied_from)` for every begin and end node, where `partner` is a begin's end (0
    for an end), and `copied_from` the uid of the node a copy was just made from (0 for a node that wasn't). A
    copy holds its original's partner, so a copied begin pairs with that end's copy when the end was copied with
    it, and is unpaired otherwise. A begin whose end is gone is unpaired.
    """
    uids = {uid for uid, _, _ in nodes}
    copy_of = {copied_from: uid for uid, _, copied_from in nodes if copied_from}
    changed: dict[int, int] = {}
    for uid, partner, copied_from in nodes:
        if not partner:
            continue
        new = copy_of.get(partner, 0) if copied_from else (partner if partner in uids else 0)
        if new != partner:
            changed[uid] = new
    return changed


def orphaned_partners(deleted: list[tuple[int, int]], nodes: list[tuple[int, int]]) -> set[int]:
    """The begin and end nodes to delete because their partner was deleted.

    `deleted` holds `(uid, partner)` for each begin and end node just deleted, and `nodes` the same for each begin
    and end node still in the tree; `partner` is a begin's end, and 0 for an end. A deleted begin takes its end with
    it, and a deleted end takes the begin paired with it.
    """
    deleted_uids = {uid for uid, _ in deleted}
    deleted_partners = {partner for _, partner in deleted if partner}
    return {
        uid
        for uid, partner in nodes
        if uid not in deleted_uids and (uid in deleted_partners or (partner and partner in deleted_uids))
    }
