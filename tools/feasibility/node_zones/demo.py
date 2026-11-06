"""A windowed run of the zones add-on: a demo tree, pairing through Blender's own operators, and screenshots.

Run with ``blender --factory-startup --enable-event-simulate <blank.blend> --python
tools/feasibility/node_zones/demo.py -- <out_dir>``. A .blend on the command line skips the splash screen, which
would cover the screenshots.
"""

from __future__ import annotations

import pathlib
import statistics
import sys
import traceback
from typing import TYPE_CHECKING, Any

import bpy

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import addon  # noqa: E402 (found through the path inserted above when run as a script)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

OUT = pathlib.Path(sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else ".")
FOREACH, VARIANT = "FOREACH_PRIM", "VARIANT_EDIT"


def _node(tree: Any, idname: str, x: float, y: float, name: str = "") -> Any:
    node = tree.nodes.new(idname)
    node.location = (x, y)
    if name:
        node.name = node.label = name
    return node


def build_demo(tree: Any) -> dict[str, Any]:
    """Stage Input → For Each Prim [Set Attribute → Variant Edit [Select Variant] → Transform] → Stage Output."""
    n: dict[str, Any] = {}
    n["input"] = _node(tree, "POC_ZONES_stage_input", -700, 0, "Stage Input")
    n["each"] = addon.add_zone(tree, FOREACH, (-450, 0), (950, 0))
    n["each_end"] = next(node for node in tree.nodes if node.uid == n["each"].partner)
    n["set"] = _node(tree, "POC_ZONES_set_attribute", -200, 40, "Set Attribute")
    n["variant"] = addon.add_zone(tree, VARIANT, (50, 40), (500, 40))
    n["variant_end"] = next(node for node in tree.nodes if node.uid == n["variant"].partner)
    n["select"] = _node(tree, "POC_ZONES_select_variant", 270, 60, "Select Variant")
    n["value"] = _node(tree, "POC_ZONES_value", 270, -140, "Value (only used inside)")
    n["transform"] = _node(tree, "POC_ZONES_transform", 730, 40, "Transform")
    n["output"] = _node(tree, "POC_ZONES_stage_output", 1200, 0, "Stage Output")
    n["leak"] = _node(tree, "POC_ZONES_transform", 100, -330, "Leaks out")
    n["loose"] = _node(tree, "POC_ZONES_set_attribute", 120, 420, "Collapsed member")
    n["loose"].hide = True
    frame = tree.nodes.new("NodeFrame")
    frame.label = "A frame"
    frame.location = (680, -150)
    n["framed"] = _node(tree, "POC_ZONES_value", 0, 0, "Value in a frame")
    n["framed"].parent = frame
    n["framed"].location = (20, -40)  # relative to the frame
    n["stray"] = _node(tree, "POC_ZONES_foreach_prim_begin", -450, -450, "Unpaired begin")

    for a, b in ((n["each"], n["each_end"]), (n["variant"], n["variant_end"])):
        tree.links.remove(next(link for link in tree.links if link.from_node == a and link.to_node == b))
    chain = ["input", "each", "set", "variant", "select", "variant_end", "transform", "each_end", "output"]
    for a, b in zip(chain, chain[1:], strict=False):
        tree.links.new(n[a].outputs[0], n[b].inputs[0])
    tree.links.new(n["value"].outputs[0], n["select"].inputs[0])
    tree.links.new(n["set"].outputs[0], n["leak"].inputs[0])
    tree.links.new(n["leak"].outputs[0], n["output"].inputs[0])
    tree.links.new(n["set"].outputs[0], n["loose"].inputs[0])
    tree.links.new(n["loose"].outputs[0], n["transform"].inputs[0])
    tree.links.new(n["framed"].outputs[0], n["transform"].inputs[0])
    return n


def build_large(tree: Any, zones: int, per_zone: int) -> None:
    """Zones in a row, each holding a chain, every other one with a nested zone."""
    previous = _node(tree, "POC_ZONES_stage_input", 0, 0)
    x = 250.0
    for z in range(zones):
        y = (z % 4) * 600.0
        begin = addon.add_zone(tree, FOREACH, (x, y), (x, y))
        end = next(node for node in tree.nodes if node.uid == begin.partner)
        tree.links.new(previous.outputs[0], begin.inputs[0])
        last = begin
        for i in range(per_zone):
            node = _node(tree, "POC_ZONES_transform", x + 200 + i * 200, y + (i % 3) * 120)
            tree.links.new(last.outputs[0], node.inputs[0])
            last = node
        end.location = (x + 200 + per_zone * 200, y)
        tree.links.new(last.outputs[0], end.inputs[0])
        x += 400 + per_zone * 200
        previous = end


class Demo:
    window: Any
    area: Any
    region: Any

    def __init__(self) -> None:
        wm: Any = bpy.context.window_manager  # never None while Blender runs timers
        self.window = wm.windows[0]
        self.area = max(self.window.screen.areas, key=lambda a: a.width * a.height)

    def override(self) -> Any:
        override: Any = bpy.context.temp_override(window=self.window, area=self.area, region=self.region)
        return override  # the stubs miss its context manager methods

    def shot(self, name: str) -> None:
        # A screenshot reads the window as of the swap before last, so draw twice first.
        with self.override():
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
        override: Any = bpy.context.temp_override(window=self.window)
        with override:
            bpy.ops.screen.screenshot(filepath=str(OUT / f"{name}.png"))
        print(f"screenshot {name}.png", flush=True)

    def show(self, tree: Any) -> None:
        self.area.spaces.active.node_tree = tree
        self.area.tag_redraw()

    def frame_all(self) -> None:
        with self.override():
            bpy.ops.node.view_all()

    def press(self, key: str, ctrl: bool = False, shift: bool = False) -> None:
        x, y = self.region.x + self.region.width // 2, self.region.y + self.region.height // 2
        self.window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=x, y=y)
        self.window.event_simulate(type=key, value="PRESS", x=x, y=y, ctrl=ctrl, shift=shift)
        self.window.event_simulate(type=key, value="RELEASE", x=x, y=y, ctrl=ctrl, shift=shift)

    def select(self, tree: Any, nodes: list[Any]) -> None:
        for node in tree.nodes:
            node.select = node in nodes
        tree.nodes.active = nodes[0]

    def zone_nodes(self, tree: Any) -> list[tuple[str, int, int]]:
        return sorted((node.name, node.uid, node.partner) for node in tree.nodes if hasattr(node, "partner"))


def _node_groups() -> Any:
    return bpy.data.node_groups  # the stubs only know Blender's own tree types


def _zone_names(tree: Any) -> list[str]:
    """The begin and end nodes' names."""
    roles = (addon.zone_model.ZoneRole.BEGIN, addon.zone_model.ZoneRole.END)
    return sorted(node.name for node in tree.nodes if getattr(node, "zone_role", None) in roles)


def _pairs(tree: Any) -> dict[str, str]:
    """Each begin's name to its end's name."""
    by_uid = {node.uid: node for node in tree.nodes if hasattr(node, "uid")}
    return {
        node.name: by_uid[node.partner].name if node.partner in by_uid else "-"
        for node in tree.nodes
        if getattr(node, "zone_role", None) is addon.zone_model.ZoneRole.BEGIN
    }


def steps() -> Iterator[float]:
    demo = Demo()
    demo.area.type = "NODE_EDITOR"
    yield 0.3
    demo.area.spaces.active.tree_type = addon.TREE_IDNAME
    demo.region = next(region for region in demo.area.regions if region.type == "WINDOW")
    node_groups = _node_groups()
    tree = node_groups.new("Zones demo", addon.TREE_IDNAME)
    n = build_demo(tree)
    demo.show(tree)
    yield 0.5
    demo.frame_all()
    yield 1.0
    demo.shot("1_demo")
    result = addon.zone_layout(tree)
    names = {node.uid: node.name for node in tree.nodes if hasattr(node, "uid")}
    for zone in result.zones:
        body = sorted(names[uid] for uid in zone.body)
        print(f"zone {names[zone.begin]} -> {names[zone.end]}, depth {zone.depth}: {body}")
    print("problems:", result.problems)
    print("invalid links:", [(link.from_node.name, link.to_node.name) for link in tree.links if not link.is_valid])
    print(f"collapsed node dimensions {tuple(n['loose'].dimensions)}")
    print(f"framed node at {tuple(n['framed'].location_absolute)}")

    # A zone takes its begin's custom color, else its end's, else its kind's.
    n["variant"].color = (0.8, 0.4, 0.1)
    n["each"].use_custom_color = n["each_end"].use_custom_color = False
    yield 0.2
    demo.shot("1b_recolored")
    _, _, colors = addon.node_rects(tree)
    for zone in addon.zone_layout(tree).zones:
        print(f"zone {names[zone.begin]} color {tuple(round(c, 2) for c in addon.zone_color(zone, colors))}")
    n["each"].use_custom_color = n["each_end"].use_custom_color = True

    # The add-zone and pair operators, as the Add menu and the sidebar call them.
    before = set(tree.nodes)
    demo.area.spaces.active.cursor_location = (-450.0, -700.0)
    with demo.override():
        bpy.ops.poc_zones.add_zone(kind=VARIANT)  # ty: ignore[unresolved-attribute]
    added = [node for node in tree.nodes if node not in before]
    print(f"add_zone made {sorted(node.name for node in added)}; pairs now {_pairs(tree)}")
    other_kind = next(node for node in added if node.zone_role is addon.zone_model.ZoneRole.END)
    lone_end = _node(tree, "POC_ZONES_foreach_prim_end", -100, -450, "Lone end")
    added.append(lone_end)
    for end in (other_kind, lone_end):  # the unpaired For Each Prim begin, with a Variant Edit end, then its own kind
        demo.select(tree, [n["stray"], end])
        try:
            with demo.override():
                outcome = bpy.ops.poc_zones.pair()  # ty: ignore[unresolved-attribute]
        except RuntimeError as error:  # an operator's ERROR report raises when called from Python
            outcome = str(error).strip()
        print(f"pair the unpaired begin with {end.name}: {outcome}; its partner {n['stray'].partner}")
    for name in [node.name for node in added]:
        if name in tree.nodes:  # removing a begin or end removes its partner with it
            tree.nodes.remove(tree.nodes[name])
    print(f"after removing them: {_zone_names(tree)}")

    # Shift-D over the whole outer zone: the copies should pair with each other.
    members = [node for node in tree.nodes if node.name not in ("Stage Input", "Stage Output", "Unpaired begin")]
    members = [node for node in members if node.bl_idname != "NodeFrame" and node.name != "Leaks out"]
    members = [node for node in members if node.name != "Value in a frame"]
    before = set(tree.nodes)
    demo.select(tree, members)
    with demo.override():
        bpy.ops.node.duplicate()
        bpy.ops.transform.translate(value=(0, -900, 0))
    copies = [node for node in tree.nodes if node not in before]
    print(f"duplicated {len(copies)} nodes; pairs now {_pairs(tree)}")
    yield 0.2
    demo.frame_all()
    yield 0.8
    demo.shot("2_duplicated")

    # Shift-D on one begin: the copy should be unpaired.
    before = set(tree.nodes)
    demo.select(tree, [n["variant"]])
    with demo.override():
        bpy.ops.node.duplicate()
    (lone,) = [node for node in tree.nodes if node not in before]
    print(f"duplicated one begin: copy {lone.name} partner {lone.partner}, original partner {n['variant'].partner}")

    # Copy and paste the original inner zone.
    before = set(tree.nodes)
    demo.select(tree, [n["variant"], n["select"], n["variant_end"]])
    with demo.override():
        bpy.ops.node.clipboard_copy()
        bpy.ops.node.clipboard_paste(offset=(0.0, 1200.0))
    pasted = [node for node in tree.nodes if node not in before]
    print(f"pasted {[node.name for node in pasted]}; pairs now {_pairs(tree)}")

    # Delete the inner zone's end with X: its begin goes too. Then undo with Ctrl+Z and redo with Ctrl+Shift+Z, as
    # keys: operators called from a timer push no undo steps, so `bpy.ops.ed.undo` would go back past them.
    demo.press("A")  # select all, a step to undo back to: the demo's own changes, made from a timer, pushed none
    yield 0.3
    demo.select(tree, [n["variant_end"]])
    demo.press("X")
    yield 0.3
    print(f"deleted the inner zone's end: {_zone_names(tree)}")
    demo.press("Z", ctrl=True)
    yield 0.3
    tree = _node_groups()["Zones demo"]  # undo replaces Blender data; Python references from before it are stale
    print(f"after undo: {_zone_names(tree)}; pairs {_pairs(tree)}")
    demo.press("Z", ctrl=True, shift=True)
    yield 0.3
    tree = _node_groups()["Zones demo"]
    print(f"after redo: {_zone_names(tree)}")
    demo.press("Z", ctrl=True)
    yield 0.3
    tree = _node_groups()["Zones demo"]

    # Deleting a begin from Python takes its end; deleting both halves at once deletes just those two.
    begin: Any = next(node for node in tree.nodes if node.name == "Variant Edit Begin.003")
    tree.nodes.remove(begin)
    yield 0.2
    print(f"removed the pasted begin from Python: {_zone_names(tree)}")
    pair = [node for node in tree.nodes if node.name in ("For Each Prim Begin.001", "For Each Prim End.001")]
    demo.select(tree, pair)
    demo.press("X")
    yield 0.3
    print(f"deleted a duplicated zone's begin and end together: {_zone_names(tree)}")
    demo.press("Z", ctrl=True)
    yield 0.3
    tree = _node_groups()["Zones demo"]
    print(f"after undo: {_zone_names(tree)}; cached layouts {len(addon._State.layouts)}")  # noqa: SLF001

    # Collapse and expand a member: the fill should follow on the next draw.
    member = next(node for node in tree.nodes if node.name == "Set Attribute")
    member.hide = True
    demo.frame_all()
    yield 0.6
    demo.shot("3_after_undo_collapsed")
    member.hide = False

    # Draw cost on a larger tree.
    for zones, per_zone in ((10, 10), (40, 20)):
        large = node_groups.new(f"Large {zones}", addon.TREE_IDNAME)
        build_large(large, zones, per_zone)
        demo.show(large)
        yield 0.3
        demo.frame_all()
        yield 0.5
        state = addon._State  # noqa: SLF001 - the demo reads the add-on's timing and drops its cache
        dragged = next(node for node in large.nodes if node.bl_idname == "POC_ZONES_transform")
        for case in ("batches reused", "one node moved per draw", "every zone remade"):
            state.draw_ns.clear()
            for i in range(30):
                if case == "every zone remade":
                    state.drawn.clear()
                elif case == "one node moved per draw":
                    dragged.location.x += 1 if i % 2 else -1  # as in a drag: one node's bounds change
                with demo.override():
                    bpy.ops.wm.redraw_timer(type="DRAW", iterations=1)
            ms = statistics.median(state.draw_ns) / 1e6
            print(f"{len(large.nodes)} nodes, {zones} zones, {case}: zone fill {ms:.2f} ms per draw (median of 30)")
        demo.shot(f"4_large_{zones}")
    addon.unregister()  # drops the cached batches; Blender reports GPU batches still held at quit as unfreed memory


def _driver(steps: Iterator[float]) -> Callable[[], float | None]:
    def run() -> float | None:
        try:
            return next(steps)
        except StopIteration:
            pass
        except Exception:  # noqa: BLE001 - report, then quit, so a failed run doesn't hang
            traceback.print_exc()
        sys.stdout.flush()
        bpy.ops.wm.quit_blender()
        return None

    return run


if __name__ == "__main__":
    addon.register()
    bpy.app.timers.register(_driver(steps()), first_interval=1.0)
