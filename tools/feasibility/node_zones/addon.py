"""Proof of concept: zones in a custom node tree, paired by uid and outlined with the gpu module.

Blender's zones (simulation, repeat, for-each element, closure) are built-in node types that a Python tree can't
hold, and no API registers a new zone type. This add-on makes its own: a begin node stores its end's uid,
`zone_model` works out what each zone holds from the links, and a `PRE_VIEW` draw handler fills a rounded convex
hull around each zone's nodes, under the nodes.

Run with ``blender --python tools/feasibility/node_zones/addon.py``, then open a node editor on the "Zone Tree"
type and add nodes from Add > Zones.
"""

from __future__ import annotations

import pathlib
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, override

import bpy
import gpu
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import zone_hull  # noqa: E402 (found through the path inserted above when run as a script)
import zone_model  # noqa: E402

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

TREE_IDNAME = "POC_ZONES_tree"
PAD = 18.0  # view units (before UI scale) around each node
NEST_PAD = 14.0  # more, per nested level
RADIUS = 14.0
OUTLINE_WIDTH = 1.5  # pixels
FILL_ALPHA = 0.3
OUTLINE_LIGHTEN = 0.35  # how far the outline goes from the zone's color toward white


Color = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class ZoneKind:
    """A kind of zone: its node names and the color its nodes and outline start with."""

    identifier: str
    label: str
    color: Color

    @property
    def node_color(self) -> Color:
        """The color its begin and end nodes start with, darker so their labels stay readable."""
        red, green, blue = (channel * 0.6 for channel in self.color)
        return red, green, blue


ZONE_KINDS = (
    ZoneKind("FOREACH_PRIM", "For Each Prim", (0.55, 0.35, 0.85)),
    ZoneKind("VARIANT_EDIT", "Variant Edit", (0.25, 0.65, 0.55)),
)


# Runtime state, rebuilt on demand: never saved, and dropped whenever the tree's data may have changed under it.
class _ZoneRuntimeState:
    """The node-zone caches, pending updates, and registered handlers."""

    layouts: ClassVar[dict[int, _CachedZoneTopology]] = {}  # by tree session_uid
    drawn: ClassVar[dict[int, _ZoneDrawData]] = {}  # the batches the last fill drew, by tree session_uid
    pending_marks: ClassVar[set[str]] = set()  # trees whose links a timer will mark
    deleted: ClassVar[dict[int, list[tuple[int, int]]]] = {}  # begins and ends just freed, by tree session_uid
    # Each node's last size, by tree session_uid then node uid. Undo rebuilds the nodes, whose `dimensions` then
    # read 0 until they draw again; uids and session_uid survive undo, so the sizes are kept across it.
    sizes: ClassVar[dict[int, dict[int, tuple[float, float]]]] = {}
    redraw_pending: ClassVar[bool] = False
    handlers: ClassVar[list[Any]] = []
    keymap_items: ClassVar[list[tuple[Any, Any]]] = []
    draw_ns: ClassVar[list[int]] = []  # each fill's time, for the demo's timing


# --- The tree and its nodes ---------------------------------------------------------------------------------------


class ZoneTree(bpy.types.NodeTree):
    """A node tree whose zones this add-on tracks."""

    bl_idname = TREE_IDNAME
    bl_label = "Zone Tree"
    bl_icon = "NODETREE"

    next_uid: bpy.props.IntProperty(default=1)  # ty: ignore[invalid-type-form]

    def new_uid(self) -> int:
        uid = self.next_uid
        self.next_uid += 1
        return uid

    @override
    def update(self) -> None:
        remove_orphans(self)
        repair_pairs(self)
        refresh_layout(self)
        # Blender sets every link's validity after this returns, so links are marked from a timer just after.
        if self.name not in _ZoneRuntimeState.pending_marks:
            _ZoneRuntimeState.pending_marks.add(self.name)
            name = self.name
            bpy.app.timers.register(lambda: _mark_later(name), first_interval=0.0)


class ZoneNodeBase:
    """What every node in the tree holds: its uid, and a begin's end."""

    zone_role: ClassVar[zone_model.ZoneRole] = zone_model.ZoneRole.PLAIN
    zone_kind: ClassVar[str] = ""
    default_color: ClassVar[Color | None] = None  # a begin or end node's color when it's added

    uid: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]
    partner_uid: bpy.props.IntProperty()  # ty: ignore[invalid-type-form] - a begin's end's uid; 0 when unpaired
    copied_from: bpy.props.IntProperty()  # ty: ignore[invalid-type-form] - set by copy until the tree repairs pairs

    @classmethod
    def poll(cls, ntree: Any) -> bool:
        return ntree.bl_idname == TREE_IDNAME

    def init(self, context: Any) -> None:
        self.uid = self.id_data.new_uid()  # ty: ignore[unresolved-attribute]
        if self.default_color is not None:
            self.use_custom_color = True
            self.color = self.default_color
        self.build_sockets()

    def free(self) -> None:
        # Blender calls this as it deletes the node; the tree's update, which follows, deletes its partner.
        if self.zone_role in _ZONE_ROLES:
            tree: Any = self.id_data  # ty: ignore[unresolved-attribute] - a Node's, through the mixin
            _ZoneRuntimeState.deleted.setdefault(tree.session_uid, []).append((self.uid, self.partner_uid))

    def copy(self, node: Any) -> None:
        # Duplicating and pasting both copy; the copy keeps the original's partner until the tree repairs it.
        self.copied_from = node.uid
        self.uid = self.id_data.new_uid()  # ty: ignore[unresolved-attribute]

    def build_sockets(self) -> None:
        self.inputs.new("NodeSocketGeometry", "Prims", use_multi_input=True)  # ty: ignore[unresolved-attribute]
        self.outputs.new("NodeSocketGeometry", "Prims")  # ty: ignore[unresolved-attribute]

    def draw_buttons_ext(self, context: Any, layout: Any) -> None:
        layout.label(text=f"uid {self.uid}, partner {self.partner_uid}")


def _plain_node_type(idname: str, label: str, role: zone_model.ZoneRole = zone_model.ZoneRole.PLAIN) -> type[Any]:
    return type(idname, (ZoneNodeBase, bpy.types.Node), {"bl_idname": idname, "bl_label": label, "zone_role": role})


PLAIN_NODES = [
    _plain_node_type("POC_ZONES_stage_input", "Stage Input", zone_model.ZoneRole.PINNED),
    _plain_node_type("POC_ZONES_stage_output", "Stage Output", zone_model.ZoneRole.PINNED),
    _plain_node_type("POC_ZONES_set_attribute", "Set Attribute"),
    _plain_node_type("POC_ZONES_transform", "Transform"),
    _plain_node_type("POC_ZONES_select_variant", "Select Variant"),
    _plain_node_type("POC_ZONES_value", "Value"),
]


def _zone_node(kind: ZoneKind, role: zone_model.ZoneRole) -> type[Any]:
    side = "Begin" if role is zone_model.ZoneRole.BEGIN else "End"
    idname = f"POC_ZONES_{kind.identifier.lower()}_{side.lower()}"
    attributes = {"bl_idname": idname, "bl_label": f"{kind.label} {side}", "zone_role": role}
    attributes["zone_kind"] = kind.identifier
    attributes["default_color"] = kind.node_color
    return type(idname, (ZoneNodeBase, bpy.types.Node), attributes)


ZONE_NODES = {
    (kind.identifier, role): _zone_node(kind, role)
    for kind in ZONE_KINDS
    for role in (zone_model.ZoneRole.BEGIN, zone_model.ZoneRole.END)
}


def _graph(tree: Any) -> tuple[list[zone_model.GraphNode], list[zone_model.GraphLink], list[Any]]:
    nodes = [
        zone_model.GraphNode(node.uid, node.zone_role, node.zone_kind, node.partner_uid)
        for node in tree.nodes
        if isinstance(node, ZoneNodeBase)
    ]
    uids = {node.as_pointer(): node.uid for node in tree.nodes if isinstance(node, ZoneNodeBase)}
    links, kept = [], []
    for link in tree.links:
        # A reroute or frame has no uid; links through reroutes are left out of the prototype.
        from_uid, to_uid = uids.get(link.from_node.as_pointer()), uids.get(link.to_node.as_pointer())
        if from_uid is not None and to_uid is not None:
            links.append(zone_model.GraphLink(from_uid, to_uid))
            kept.append(link)
    return nodes, links, kept


@dataclass(frozen=True, slots=True)
class _CachedZoneTopology:
    """A tree's zones, and the graph they were worked out from."""

    nodes: list[zone_model.GraphNode]
    links: list[zone_model.GraphLink]
    zones: zone_model.ZoneLayout


def refresh_layout(tree: Any) -> zone_model.ZoneLayout:
    """Work out the tree's zones again if its links or pairs changed.

    The tree's update runs on every change, a node moved from Python included, and positions don't change zones.
    """
    nodes, links, _ = _graph(tree)
    cached = _ZoneRuntimeState.layouts.get(tree.session_uid)
    if cached is None or cached.nodes != nodes or cached.links != links:
        cached = _ZoneRuntimeState.layouts[tree.session_uid] = _CachedZoneTopology(
            nodes, links, zone_model.layout(nodes, links)
        )
    return cached.zones


def zone_layout(tree: Any) -> zone_model.ZoneLayout:
    """The tree's zones, worked out once per change to its links or pairs."""
    cached = _ZoneRuntimeState.layouts.get(tree.session_uid)
    return refresh_layout(tree) if cached is None else cached.zones


def remove_orphans(tree: Any) -> None:
    """Delete each begin or end node whose partner was deleted other than by the zone delete keys.

    This runs after the delete has pushed its undo step, so the partner's removal is a step of its own.
    """
    deleted = _ZoneRuntimeState.deleted.pop(tree.session_uid, [])
    if not deleted:
        return
    zone_nodes = [node for node in tree.nodes if getattr(node, "zone_role", None) in _ZONE_ROLES]
    orphans = zone_model.orphaned_partners(deleted, [(node.uid, node.partner_uid) for node in zone_nodes])
    for node in zone_nodes:
        if node.uid in orphans:
            tree.nodes.remove(node)  # its own free records it, and the update this causes finds nothing more


def repair_pairs(tree: Any) -> None:
    """Pair copied begins with their ends' copies, and unpair begins whose end is gone."""
    zone_nodes = [node for node in tree.nodes if getattr(node, "zone_role", None) in _ZONE_ROLES]
    changed = zone_model.repaired_partners([(node.uid, node.partner_uid, node.copied_from) for node in zone_nodes])
    for node in zone_nodes:
        if node.uid in changed:
            node.partner_uid = changed[node.uid]
        if node.copied_from:
            node.copied_from = 0


_ZONE_ROLES = (zone_model.ZoneRole.BEGIN, zone_model.ZoneRole.END)


def _mark_later(tree_name: str) -> None:
    _ZoneRuntimeState.pending_marks.discard(tree_name)
    node_groups: Any = bpy.data.node_groups
    tree = node_groups.get(tree_name)
    if tree is not None and tree.bl_idname == TREE_IDNAME:
        mark_links(tree)


def mark_links(tree: Any) -> None:
    """Draw links that cross out of a zone as invalid (red)."""
    _, _, kept = _graph(tree)
    invalid = zone_layout(tree).invalid_link_indices
    for position, link in enumerate(kept):
        valid = position not in invalid
        if link.is_valid != valid:
            link.is_valid = valid


# --- Operators and UI ---------------------------------------------------------------------------------------------


def _in_zone_tree(context: Any) -> bool:
    space = context.space_data
    return getattr(space, "edit_tree", None) is not None and space.edit_tree.bl_idname == TREE_IDNAME


class POC_ZONES_OT_add_zone(bpy.types.Operator):
    """Add a paired begin and end node, linked, at the cursor."""

    bl_idname = "poc_zones.add_zone"
    bl_label = "Add Zone"
    bl_options = {"REGISTER", "UNDO"}

    kind: bpy.props.EnumProperty(items=[(k.identifier, k.label, "") for k in ZONE_KINDS])  # ty: ignore[invalid-type-form]

    @override
    @classmethod
    def poll(cls, context: Any) -> bool:
        return _in_zone_tree(context)

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        tree = context.space_data.edit_tree
        x, y = context.space_data.cursor_location
        add_zone(tree, self.kind, (x - 150, y), (x + 150, y))
        return {"FINISHED"}


def add_zone(tree: Any, kind: str, begin_at: tuple[float, float], end_at: tuple[float, float]) -> Any:
    """A new zone's begin node, paired and linked with its new end node."""
    for node in tree.nodes:
        node.select = False
    begin = tree.nodes.new(ZONE_NODES[kind, zone_model.ZoneRole.BEGIN].bl_idname)
    end = tree.nodes.new(ZONE_NODES[kind, zone_model.ZoneRole.END].bl_idname)
    begin.location, end.location = begin_at, end_at
    begin.partner_uid = end.uid
    tree.links.new(begin.outputs[0], end.inputs[0])
    tree.nodes.active = begin
    return begin


class POC_ZONES_OT_delete(bpy.types.Operator):
    """Delete the selected nodes, and the other half of each zone among them."""

    bl_idname = "poc_zones.delete"
    bl_label = "Delete"
    bl_options = {"REGISTER", "UNDO"}

    reconnect: bpy.props.BoolProperty()  # ty: ignore[invalid-type-form] - keep links through the deleted nodes

    @override
    @classmethod
    def poll(cls, context: Any) -> bool:
        return _in_zone_tree(context)  # elsewhere, the key falls through to Blender's own delete

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        # Selecting the partners first puts them in Blender's delete, so the delete and the partners' removal are
        # one undo step. The tree's update only catches what deletes some other way, as a step of its own.
        tree = context.space_data.edit_tree
        select_partners(tree)
        if self.reconnect:
            bpy.ops.node.delete_reconnect()
        else:
            bpy.ops.node.delete()
        return {"FINISHED"}


def select_partners(tree: Any) -> None:
    """Select the other half of each selected zone."""
    zone_nodes = [node for node in tree.nodes if getattr(node, "zone_role", None) in _ZONE_ROLES]
    selected = [(node.uid, node.partner_uid) for node in zone_nodes if node.select]
    remaining = [(node.uid, node.partner_uid) for node in zone_nodes if not node.select]
    partners = zone_model.orphaned_partners(selected, remaining)
    for node in zone_nodes:
        if node.uid in partners:
            node.select = True


class POC_ZONES_OT_pair(bpy.types.Operator):
    """Pair the active begin node with the other selected end node of its kind."""

    bl_idname = "poc_zones.pair"
    bl_label = "Pair Zone Nodes"
    bl_options = {"REGISTER", "UNDO"}

    @override
    @classmethod
    def poll(cls, context: Any) -> bool:
        active = context.active_node
        return _in_zone_tree(context) and getattr(active, "zone_role", None) is zone_model.ZoneRole.BEGIN

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        begin: Any = context.active_node
        ends = [
            node
            for node in context.selected_nodes
            if getattr(node, "zone_role", None) is zone_model.ZoneRole.END and node.zone_kind == begin.zone_kind
        ]
        if len(ends) != 1:
            self.report({"ERROR"}, "Select exactly one end node of the same kind")
            return {"CANCELLED"}
        for other in begin.id_data.nodes:  # an end has one begin
            if getattr(other, "partner_uid", 0) == ends[0].uid:
                other.partner_uid = 0
        begin.partner_uid = ends[0].uid
        begin.id_data.update_tag()
        return {"FINISHED"}


class POC_ZONES_PT_zone(bpy.types.Panel):
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Zones"
    bl_label = "Zone"

    @override
    @classmethod
    def poll(cls, context: Any) -> bool:
        return _in_zone_tree(context)

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout  # never None while drawing
        tree = context.space_data.edit_tree
        result = zone_layout(tree)
        by_uid = {node.uid: node for node in tree.nodes if isinstance(node, ZoneNodeBase)}
        active: Any = context.active_node
        if isinstance(active, ZoneNodeBase):
            zone = result.innermost_zone_by_node_uid.get(active.uid)
            layout.label(text=f"{active.name}: uid {active.uid}")
            if zone is None:
                layout.label(text="Not in a zone")
            else:
                begin, end = by_uid.get(zone.begin_uid), by_uid.get(zone.end_uid)
                layout.label(text=f"In {begin.name if begin else '?'} → {end.name if end else '?'}", icon="NODE")
                layout.label(text=f"Depth {zone.depth}, {len(zone.body_node_uids)} nodes inside")
        layout.operator(POC_ZONES_OT_pair.bl_idname)
        for problem in result.problems:
            layout.label(text=problem, icon="ERROR")


def _draw_add_menu(self: Any, context: Any) -> None:
    if not _in_zone_tree(context):
        return
    layout: Any = self.layout
    layout.separator()
    for kind in ZONE_KINDS:
        layout.operator(POC_ZONES_OT_add_zone.bl_idname, text=f"{kind.label} Zone").kind = kind.identifier
    for cls in PLAIN_NODES:
        layout.operator("node.add_node", text=cls.bl_label).type = cls.bl_idname


# --- Drawing ------------------------------------------------------------------------------------------------------


def node_rects(tree: Any) -> tuple[dict[int, zone_hull.Rect], set[int], dict[int, Color]]:
    """Each node's bounds in view space, the selected nodes' uids, and the custom colors of the nodes that have one.

    `location_absolute` is in node units and is scaled by the UI scale; `dimensions` is already in view units.
    `dimensions` is the size the node had when last drawn: 0 before its first draw and after an undo, and a frame
    behind after it changes size. A node that reads 0 gets the last size it had.
    """
    scale = _ui_scale()
    rects: dict[int, zone_hull.Rect] = {}
    selected: set[int] = set()
    colors: dict[int, Color] = {}
    sizes = _ZoneRuntimeState.sizes.setdefault(tree.session_uid, {})
    for node in tree.nodes:
        if not isinstance(node, ZoneNodeBase):
            continue
        x, y = node.location_absolute
        width, height = node.dimensions
        if width and height:
            sizes[node.uid] = (width, height)
        else:
            width, height = sizes.get(node.uid, (0.0, 0.0))
        left, top = x * scale, y * scale
        rects[node.uid] = zone_hull.Rect(left, top - height, left + width, top)
        if node.select:
            selected.add(node.uid)
        if node.use_custom_color:
            colors[node.uid] = tuple(node.color)
    return rects, selected, colors


def zone_color(zone: zone_model.Zone, colors: dict[int, Color]) -> Color:
    """A zone's color: its begin node's custom color, else its end node's, else its kind's."""
    kinds = {kind.identifier: kind.node_color for kind in ZONE_KINDS}
    return colors.get(zone.begin_uid) or colors.get(zone.end_uid) or kinds.get(zone.kind, (0.5, 0.5, 0.5))


def _lighter(color: Color, amount: float) -> Color:
    red, green, blue = (channel + (1.0 - channel) * amount for channel in color)
    return red, green, blue


@dataclass(slots=True)
class _DrawnZone:
    """One zone's core and batches, and the bounds they were made from."""

    geometry_cache_key: tuple[Any, ...]  # its core nodes' bounds, and its nested zones' keys
    hull_points: list[zone_hull.Point]
    gpu_batches: tuple[Any, Any] | None  # fill and outline; None when it has too few points to draw


@dataclass(slots=True)
class _ZoneDrawData:
    """A tree's zones as drawn, and what they were made from."""

    layout: zone_model.ZoneLayout
    scale: float
    rects: dict[int, zone_hull.Rect]
    core_nodes: dict[int, list[int]]  # the nodes each zone's core takes directly, by its begin
    zones: dict[int, _DrawnZone]  # by begin


def _build_zone_draw_data(tree: Any, rects: dict[int, zone_hull.Rect]) -> _ZoneDrawData:
    """Build or reuse cached zone draw data, rebuilding zones whose node bounds changed.

    So a drag remakes the zones holding the dragged node and keeps the rest.
    """
    result = zone_layout(tree)
    scale = _ui_scale()
    drawn = _ZoneRuntimeState.drawn.get(tree.session_uid)
    if drawn is not None and drawn.layout is result and drawn.scale == scale:
        if drawn.rects == rects:
            return drawn
    else:
        core = {zone.begin_uid: zone_hull.core_nodes(zone, result) for zone in result.zones}
        drawn = _ZoneDrawData(result, scale, {}, core, {})
    zones: dict[int, _DrawnZone] = {}
    for zone in sorted(result.zones, key=lambda z: -z.depth):  # nested zones first
        core_rects = tuple(rects.get(uid) for uid in drawn.core_nodes[zone.begin_uid])
        children = [zones[child.begin_uid] for child in zone.children]
        key = (core_rects, tuple(child.geometry_cache_key for child in children))
        previous = drawn.zones.get(zone.begin_uid)
        if previous is not None and previous.geometry_cache_key == key:
            zones[zone.begin_uid] = previous
            continue
        core = zone_hull.zone_core(
            zone,
            result,
            _sized(rects, drawn.core_nodes[zone.begin_uid]),
            [c.hull_points for c in children if c.hull_points],
            PAD * scale,
            NEST_PAD * scale,
            RADIUS * scale,
        )
        zones[zone.begin_uid] = _DrawnZone(
            key, core, _zone_batches(zone_hull.grown(core, RADIUS * scale)) if core else None
        )
    drawn.rects, drawn.zones = rects, zones
    _ZoneRuntimeState.drawn[tree.session_uid] = drawn
    return drawn


def _sized(rects: dict[int, zone_hull.Rect], uids: list[int]) -> dict[int, zone_hull.Rect]:
    # A node not yet drawn has no size; it's left out until it has one.
    return {uid: rects[uid] for uid in uids if uid in rects and rects[uid].right > rects[uid].left}


def _zone_batches(hull: list[zone_hull.Point]) -> tuple[Any, Any] | None:
    if len(hull) < 3:
        return None
    fill = batch_for_shader(_shader("UNIFORM_COLOR"), "TRIS", {"pos": hull}, indices=zone_hull.fan_triangles(hull))
    outline = batch_for_shader(_shader("POLYLINE_UNIFORM_COLOR"), "LINE_STRIP", {"pos": [*hull, hull[0]]})
    return fill, outline


def _ui_scale() -> float:
    preferences: Any = bpy.context.preferences  # never None in a running Blender
    return preferences.system.ui_scale


def _shader(name: str) -> Any:
    return gpu.shader.from_builtin(name)


def _zone_tree_in_context() -> Any:
    space: Any = bpy.context.space_data
    tree = space.edit_tree if space else None
    return tree if tree is not None and tree.bl_idname == TREE_IDNAME else None


def _draw_zones() -> None:
    tree = _zone_tree_in_context()
    if tree is None:
        return
    start = time.perf_counter_ns()
    rects, selected, colors = node_rects(tree)
    drawn = _build_zone_draw_data(tree, rects)
    scale = _ui_scale()
    region: Any = bpy.context.region
    fill, line = _shader("UNIFORM_COLOR"), _shader("POLYLINE_UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    for zone in drawn.layout.zones:  # outer zones first, so nested ones draw over them
        batches = drawn.zones[zone.begin_uid].gpu_batches
        if batches is None:
            continue
        fill_batch, outline_batch = batches
        color = zone_color(zone, colors)
        fill.uniform_float("color", (*color, FILL_ALPHA))
        fill_batch.draw(fill)
        highlighted = zone.begin_uid in selected or zone.end_uid in selected
        line.uniform_float("viewportSize", (region.width, region.height))
        line.uniform_float("lineWidth", OUTLINE_WIDTH * scale * (2.0 if highlighted else 1.0))
        line.uniform_float("color", (*_lighter(color, OUTLINE_LIGHTEN), 0.9 if highlighted else 0.6))
        outline_batch.draw(line)
    gpu.state.blend_set("NONE")
    _ZoneRuntimeState.draw_ns.append(time.perf_counter_ns() - start)


def _check_sizes() -> None:
    # After the nodes draw, their sizes are current. If the fill used other sizes, draw once more.
    tree = _zone_tree_in_context()
    if tree is None:
        return
    drawn = _ZoneRuntimeState.drawn.get(tree.session_uid)
    if drawn is not None and drawn.rects != node_rects(tree)[0] and not _ZoneRuntimeState.redraw_pending:
        # A redraw tagged while the region draws didn't happen, so it's tagged from a timer after the draw.
        _ZoneRuntimeState.redraw_pending = True
        bpy.app.timers.register(_redraw_node_editors, first_interval=0.0)


def _redraw_node_editors() -> None:
    _ZoneRuntimeState.redraw_pending = False
    wm: Any = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == "NODE_EDITOR":
                area.tag_redraw()


@persistent
def _forget_layouts(*_: Any) -> None:
    # Undo, redo, and loading replace the tree's data without calling its update.
    _ZoneRuntimeState.layouts.clear()
    _ZoneRuntimeState.drawn.clear()
    _ZoneRuntimeState.deleted.clear()  # undo frees and rebuilds nodes; those aren't deletions


@persistent
def _forget_all(*_: Any) -> None:
    # A loaded file's trees are new, and their sizes come with their first draw.
    _forget_layouts()
    _ZoneRuntimeState.sizes.clear()


_HANDLERS = (
    (bpy.app.handlers.undo_post, _forget_layouts),
    (bpy.app.handlers.redo_post, _forget_layouts),
    (bpy.app.handlers.load_post, _forget_all),
)
CLASSES: list[Any] = [
    ZoneTree,
    *PLAIN_NODES,
    *ZONE_NODES.values(),
    POC_ZONES_OT_add_zone,
    POC_ZONES_OT_delete,
    POC_ZONES_OT_pair,
    POC_ZONES_PT_zone,
]


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.NODE_MT_add.append(_draw_add_menu)  # ty: ignore[invalid-argument-type] - the stubs want a bound draw
    space = bpy.types.SpaceNodeEditor
    _ZoneRuntimeState.handlers = [
        space.draw_handler_add(_draw_zones, (), "WINDOW", "PRE_VIEW"),
        space.draw_handler_add(_check_sizes, (), "WINDOW", "POST_VIEW"),
    ]
    for handlers, handler in _HANDLERS:
        handlers.append(handler)
    _add_keymap()


# Blender's delete keys, taken over in zone trees; the operator's poll lets them through everywhere else.
_DELETE_KEYS = (("X", False, False), ("DEL", False, False), ("X", True, True))  # key, ctrl, reconnect


def _add_keymap() -> None:
    wm: Any = bpy.context.window_manager  # never None while add-ons register
    keyconfig = wm.keyconfigs.addon
    if keyconfig is None:  # in background mode
        return
    keymap = keyconfig.keymaps.new(name="Node Editor", space_type="NODE_EDITOR")
    for key, ctrl, reconnect in _DELETE_KEYS:
        item: Any = keymap.keymap_items.new(POC_ZONES_OT_delete.bl_idname, key, "PRESS", ctrl=ctrl)
        item.properties.reconnect = reconnect
        _ZoneRuntimeState.keymap_items.append((keymap, item))


def unregister() -> None:
    _forget_all()  # the batches too: Blender would report them as unfreed memory at quit
    for keymap, item in _ZoneRuntimeState.keymap_items:
        keymap.keymap_items.remove(item)
    _ZoneRuntimeState.keymap_items = []
    for handlers, handler in _HANDLERS:
        if handler in handlers:
            handlers.remove(handler)
    for handler in _ZoneRuntimeState.handlers:
        bpy.types.SpaceNodeEditor.draw_handler_remove(handler, "WINDOW")
    _ZoneRuntimeState.handlers = []
    bpy.types.NODE_MT_add.remove(_draw_add_menu)  # ty: ignore[invalid-argument-type]
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
