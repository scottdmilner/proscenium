"""Headless check and timings for the scene graph UI PoC (``uv run python tools/feasibility/scene_graph_ui/bench.py``).

It runs in the bpy wheel, so it times the model and the RNA work behind each tree, not drawing or scrolling, which
need a window.
"""

from __future__ import annotations

import pathlib
import sys
import time
from typing import TYPE_CHECKING, Any

import bpy
from pxr import Sdf, Usd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import addon  # noqa: E402 (found through the path inserted above)
import native_tree  # noqa: E402
import prim_text  # noqa: E402
import tree_model  # noqa: E402
import tree_search  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable

OPS: Any = None  # bpy.ops.poc_sg, once registered


class OPS_PROPS:  # noqa: N801 - stands in for an operator's properties
    def __init__(self, row_index: int) -> None:
        self.row_index = row_index


def _timed(action: Callable[[], object]) -> float:
    start = time.perf_counter()
    action()
    return (time.perf_counter() - start) * 1000


def _tree() -> tree_model.StageTree:
    tree = addon._SceneGraphUiState.tree  # noqa: SLF001 (the PoC's module state)
    assert tree is not None
    return tree


def _names(tree: tree_model.StageTree, depth: int) -> list[str]:
    return [row.prim.GetName() for row in tree.rows if row.depth == depth]


def check_demo() -> None:
    wm: Any = bpy.context.window_manager
    assert OPS.open_demo() == {"FINISHED"}
    tree = _tree()
    assert _names(tree, 0) == ["_Crate", "World", "World_Override_Only"], _names(tree, 0)
    assert len(wm.poc_sg_rows) == len(tree.rows)

    # Expanding World shows its children one level deeper; a recursive expand reaches instance proxies.
    world = _names(tree, 0).index("World")
    assert OPS.toggle(row_index=world) == {"FINISHED"}
    assert _names(tree, 1) == ["Geometry", "Looks", "Camera", "Sun", "Scatter"]
    assert OPS.toggle(row_index=world, recursive=True) == {"FINISHED"}  # collapses the subtree
    assert len(tree.rows) == 3
    assert OPS.toggle(row_index=world, recursive=True) == {"FINISHED"}  # expands it all
    rows = {str(row.prim.GetPath()): tree.details(row) for row in tree.rows}
    assert len(rows) == len(list(Usd.PrimRange(tree.stage.GetPrimAtPath("/World"), tree_model.CHILD_PREDICATE))) + 2
    assert rows["/World/Geometry/Crates/Crate_01"].is_instance
    assert rows["/World/Geometry/Crates/Crate_01/Body"].is_instance_proxy
    assert rows["/World/Geometry/Prop_Payloaded"].has_payload
    assert rows["/World/Geometry/Prop_Variants"].has_variants
    assert not rows["/World/Geometry/Disabled"].active
    crate = tree.stage.GetPrimAtPath("/World/Geometry/Crates/Crate_01")
    print("tooltips:")
    print("  row:", repr(addon._row_tooltip(wm.poc_sg_rows[tree.position(crate)])))  # noqa: SLF001
    for path, badge in (
        ("/World/Geometry/Prop_Payloaded", "payload"),
        ("/World/Geometry/Crates/Crate_01", "references"),
        ("/World/Geometry/Crates/Crate_01", "instance"),
        ("/World/Geometry/Crates/Crate_01/Body", "instance"),
        ("/World/Geometry/Prop_Variants", "variants"),
    ):
        print(f"  {badge}:", prim_text.badge_tooltip(tree.stage.GetPrimAtPath(path), badge))
    assert len(wm.poc_sg_rows) == len(tree.rows)

    # Find reveals a prim inside a collapsed branch and makes its row the active one.
    assert OPS.open_demo() == {"FINISHED"}
    tree = _tree()
    assert OPS.find(text="panel") == {"FINISHED"}
    assert wm.poc_sg_active >= 0
    assert tree.rows[wm.poc_sg_active].prim.GetPath() == Sdf.Path("/_Crate/Lid/Panel")
    assert len(wm.poc_sg_rows) == len(tree.rows)

    # The native tree nests panels like prims, and maps each item back to its prim.
    assert OPS.build_native(cap=1000) == {"FINISHED"}
    interface: Any = bpy.data.node_groups[native_tree.NATIVE_TREE_NAME].interface
    paths = native_tree.paths()
    by_key = {native_tree.item_key(item): item for item in interface.items_tree}
    for key, path in paths.items():
        item = by_key[key]
        parent_path = paths.get(native_tree.item_key(item.parent)) if item.parent.name else None
        assert (parent_path or Sdf.Path.absoluteRootPath) == path.GetParentPath(), (path, parent_path)
    world_panel = next(i for i in interface.items_tree if paths[native_tree.item_key(i)] == Sdf.Path("/World"))
    native_order = [item.name for item in world_panel.interface_items]
    usd_order = tree.stage.GetPrimAtPath("/World").GetChildrenNames()
    print(f"demo ok; native tree holds {len(paths)} prims")
    print(f"  /World children, USD order:    {list(usd_order)}")
    print(f"  /World children, native order: {native_order}")


def _paths(tree: tree_model.StageTree) -> list[str]:
    return [str(row.prim.GetPath()) for row in tree.rows]


def _search(wm: Any, **fields: object) -> tree_model.StageTree:
    defaults: dict[str, object] = {"search": "", "search_mode": "NAME", "search_case": False, "search_type": ""}
    for flag in tree_search.SearchFlag:
        defaults[f"search_{flag.name.lower()}"] = False
    for name, value in {**defaults, **fields}.items():
        setattr(wm, f"poc_sg_{name}", value)
    addon.apply_search(wm)  # the timer that would run it doesn't fire without an event loop
    return _tree()


def check_search() -> None:
    wm: Any = bpy.context.window_manager
    assert OPS.open_demo() == {"FINISHED"}
    tree = _tree()
    tree.toggle(1)  # /World, the expansion to come back to
    before = _paths(tree)

    # Matches show in place, under every ancestor; ancestors that don't match are marked so.
    tree = _search(wm, search="lid")
    lids = [p for p in _paths(tree) if p.endswith("/Lid")]
    assert lids == [
        "/_Crate/Lid",
        "/World/Geometry/Crates/Crate_01/Lid",
        "/World/Geometry/Crates/Crate_02/Lid",
        "/World/Geometry/Crates/Crate_Unique/Lid",
        "/World/Geometry/Prop_Payloaded/Lid",
    ], lids
    assert "/World/Looks" not in _paths(tree)  # holds no match
    assert "/_Crate/Body" not in _paths(tree)  # a sibling of a match
    assert [tree.is_match(row) for row in tree.rows if str(row.prim.GetPath()) in ("/_Crate", "/_Crate/Lid")] == [
        False,
        True,
    ]
    # A match can be expanded to explore what's under it, unfiltered.
    lid = next(i for i, row in enumerate(tree.rows) if str(row.prim.GetPath()) == "/_Crate/Lid")
    tree.toggle(lid)
    assert _paths(tree)[lid + 1] == "/_Crate/Lid/Panel"

    assert {p for p in _paths(tree) if tree.is_match(tree.rows[_paths(tree).index(p)])} >= {"/_Crate/Lid"}
    glob = _search(wm, search="Crate_0?", search_mode="GLOB")
    assert [str(r.prim.GetPath()) for r in glob.rows if glob.is_match(r)] == [
        "/World/Geometry/Crates/Crate_01",
        "/World/Geometry/Crates/Crate_02",
    ]
    gprims = _search(wm, search_type="Gprim")  # IsA, so meshes and curves both match
    assert {r.prim.GetTypeName() for r in gprims.rows if gprims.is_match(r)} == {"Mesh", "BasisCurves"}
    payloads = _search(wm, search_payload=True)
    assert [str(r.prim.GetPath()) for r in payloads.rows if payloads.is_match(r)] == ["/World/Geometry/Prop_Payloaded"]
    _search(wm, search="(", search_mode="REGEX")
    assert addon._SceneGraphUiState.search_status.startswith("Search:"), addon._SceneGraphUiState.search_status  # noqa: SLF001

    # Clearing the search restores the expansion from before it, plus the selected prim revealed.
    addon._SceneGraphUiState.selected = tree.stage.GetPrimAtPath("/_Crate/Lid/Panel")  # noqa: SLF001
    tree = _search(wm)
    assert set(before) < set(_paths(tree))
    assert "/_Crate/Lid/Panel" in _paths(tree)
    assert wm.poc_sg_active == _paths(tree).index("/_Crate/Lid/Panel")
    assert len(wm.poc_sg_rows) == len(tree.rows)
    print("search ok")


def check_steps() -> None:
    # Right expands, then steps in; Left collapses, then steps out to the parent.
    assert OPS.open_demo() == {"FINISHED"}
    tree = _tree()
    world = _paths(tree).index("/World")
    assert tree.expand_or_enter_row(world) == world and tree.is_expanded(tree.rows[world])
    geometry = tree.expand_or_enter_row(world)
    assert _paths(tree)[geometry] == "/World/Geometry"
    assert tree.collapse_or_select_parent(geometry) == world  # Geometry is collapsed, so Left goes to its parent
    assert tree.collapse_or_select_parent(world) == world and not tree.is_expanded(tree.rows[world])
    camera_free = _paths(tree).index("/World_Override_Only")
    assert tree.collapse_or_select_parent(camera_free) == camera_free  # a top-level row has no parent to go to
    # The addon's step, as the key watcher calls it, moves the active row as the model's steps do.
    wm: Any = bpy.context.window_manager
    wm.poc_sg_active = world
    addon.step(wm, "IN", False)  # World is collapsed again, so Right expands it
    assert wm.poc_sg_active == world and tree.is_expanded(tree.rows[world])
    addon.step(wm, "IN", False)
    assert _paths(tree)[wm.poc_sg_active] == "/World/Geometry"
    addon.step(wm, "OUT", True)  # Shift+Left on a collapsed row leaves it as it is
    addon.step(wm, "OUT", False)
    assert wm.poc_sg_active == world
    addon.step(wm, "IN", True)  # Shift+Right expands the whole subtree
    assert len(tree.rows) == 31
    print("  triangle tooltip:", repr(addon.POC_SG_OT_toggle.description(bpy.context, OPS_PROPS(world))))
    print("steps ok")


def time_search() -> None:
    print("\nSearch: name contains, over every prim of the stage")
    for fanout, depth, wide in ((8, 5, 0), (2, 2, 250_000), (2, 2, 1_000_000)):
        stage = tree_model.synthetic_stage(fanout, depth, wide)
        tree = tree_model.StageTree(stage)
        for text in ("g4_3", "leaf_1"):
            query = tree_search.SearchQuery(text=text)
            start = time.perf_counter()
            result = tree_search.search(stage, query, addon.SEARCH_CAP)
            searched = (time.perf_counter() - start) * 1000
            shown = _timed(lambda: tree.set_search(result))  # noqa: B023
            prims = sum(1 for _ in Usd.PrimRange(stage.GetPseudoRoot(), tree_model.CHILD_PREDICATE))
            print(
                f"  {prims:>8} prims, {text!r:>8}: search {searched:7.1f} ms ({len(result.matches):>5} matches"
                f"{', capped' if result.truncated else ''}), rows {shown:6.1f} ms"
            )


def time_uilist() -> None:
    print("\nUIList tree: expand a group of N leaves, draw a screenful of rows, collapse it")
    wm: Any = bpy.context.window_manager
    for wide in (1_000, 10_000, 100_000, 250_000, 1_000_000):
        addon._set_stage(bpy.context, tree_model.synthetic_stage(2, 2, wide))  # noqa: SLF001
        tree = _tree()
        tree.toggle(0)  # /World
        addon._sync_rows(wm)  # noqa: SLF001
        wide_row = next(i for i, row in enumerate(tree.rows) if row.prim.GetName() == "Wide")
        expand_model = _timed(lambda: tree.toggle(wide_row))  # noqa: B023
        expand_rna = _timed(lambda: addon._sync_rows(wm))  # noqa: SLF001
        assert len(wm.poc_sg_rows) == len(tree.rows) > wide
        # A first draw reads the details of the rows on screen (40 is the panel's maxrows).
        screen = _timed(lambda: [tree.details(row) for row in tree.rows[wide_row : wide_row + 40]])  # noqa: B023
        collapse = _timed(lambda: (tree.toggle(wide_row), addon._sync_rows(wm)))  # noqa: B023, SLF001
        assert len(tree.rows) == len(wm.poc_sg_rows) < 10
        print(
            f"  N={wide:>8}: expand model {expand_model:7.1f} ms, collection add {expand_rna:7.1f} ms,"
            f" first draw details {screen:5.2f} ms, collapse {collapse:6.1f} ms"
        )


def time_native() -> None:
    print("\nNative tree: build the interface for the first N prims of a fanout-8 hierarchy")
    stage = tree_model.synthetic_stage(8, 5)  # 37449 prims
    for cap in (500, 2_000, 5_000, 10_000):
        elapsed = _timed(lambda: native_tree.build(stage, cap))  # noqa: B023
        print(f"  N={cap:>6}: {elapsed:9.1f} ms")


def main() -> None:
    print(f"Blender {bpy.app.version_string}, USD {Usd.GetVersion()}")
    global OPS
    addon.register()
    OPS = bpy.ops.poc_sg  # ty: ignore[unresolved-attribute] - registered just above
    try:
        check_demo()
        check_search()
        check_steps()
        time_uilist()
        time_search()
        time_native()
    finally:
        addon.unregister()


if __name__ == "__main__":
    main()
