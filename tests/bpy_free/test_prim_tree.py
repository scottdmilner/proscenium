"""The prim tree's rows (proscenium.ui.scene_graph_widget.prim_tree.prim_tree), on the scene graph test scene.

The scene is scenes/scene_graph/prim_kinds.usda.

Expected rows are written from how the scene is built: its top level is _Crate (a class), World, and
World_Override_Only (an over), and /World holds 33 prims, instance proxies included.
"""

from __future__ import annotations

import gc
from typing import TYPE_CHECKING

import pytest
from pxr import Sdf, Usd

from fixtures.scenes import Scene, copy_scene
from proscenium.ui.scene_graph_widget.prim_tree import PrimTree, prim_search
from support.usd import open_stage_without_cache

if TYPE_CHECKING:
    from pathlib import Path

TOP_LEVEL = ["/_Crate", "/World", "/World_Override_Only"]
WORLD_CHILDREN = ["/World/Geometry", "/World/Looks", "/World/Camera", "/World/Sun", "/World/Scatter"]
PRIMS_UNDER_WORLD = 34  # /World and everything under it


@pytest.fixture
def stage(tmp_path: Path) -> Usd.Stage:
    return open_stage_without_cache(copy_scene(Scene.SCENE_GRAPH, tmp_path) / "prim_kinds.usda")


def _paths(tree: PrimTree) -> list[str]:
    return [str(row.path) for row in tree.rows]


def _index(tree: PrimTree, path: str) -> int:
    row_index = tree.row_index(Sdf.Path(path))
    assert row_index is not None, path
    return row_index


def test_a_new_tree_shows_the_top_level_collapsed(stage: Usd.Stage) -> None:
    tree = PrimTree(stage)
    assert _paths(tree) == TOP_LEVEL
    assert [row.depth for row in tree.rows] == [0, 0, 0]
    assert not any(tree.is_expanded(row) for row in tree.rows)


def test_expanding_splices_children_in_one_level_deeper(stage: Usd.Stage) -> None:
    tree = PrimTree(stage)
    tree.toggle(_index(tree, "/World"))
    assert _paths(tree) == ["/_Crate", "/World", *WORLD_CHILDREN, "/World_Override_Only"]
    assert {row.depth for row in tree.rows[2:7]} == {1}
    tree.toggle(_index(tree, "/World"))
    assert _paths(tree) == TOP_LEVEL


def test_a_nested_instance_is_a_proxy_of_the_outer_one(tmp_path: Path) -> None:
    nested = open_stage_without_cache(copy_scene(Scene.SCENE_GRAPH, tmp_path) / "nested_instances.usda")
    tree = PrimTree(nested)
    tree.reveal(Sdf.Path("/World/Pallet/Crate/Lid"))
    details = {str(row.path): tree.details(row) for row in tree.rows}
    crate, lid = details["/World/Pallet/Crate"], details["/World/Pallet/Crate/Lid"]
    assert crate.is_instance and crate.is_instance_proxy
    assert (crate.instance_path, crate.outermost_instance_path) == (Sdf.Path("/World/Pallet"),) * 2
    assert lid.instance_path == Sdf.Path("/World/Pallet/Crate")  # the nearest, which the tooltip names
    assert lid.outermost_instance_path == Sdf.Path("/World/Pallet")  # where the guide lines' dashes start
    assert details["/World/Pallet"].outermost_instance_path is None


def test_a_recursive_expand_reaches_instance_proxies_and_collapses_back(stage: Usd.Stage) -> None:
    tree = PrimTree(stage)
    world = _index(tree, "/World")
    tree.toggle(world, recursive=True)
    assert len(tree.rows) == PRIMS_UNDER_WORLD + 2
    details = {str(row.path): tree.details(row) for row in tree.rows}
    assert details["/World/Geometry/Crates/Crate_01"].is_instance
    assert details["/World/Geometry/Crates/Crate_01/Body"].is_instance_proxy
    # A proxy's instance is the nearest instance above it, however deep the proxy is.
    assert details["/World/Geometry/Crates/Crate_01/Lid/Panel"].instance_path == Sdf.Path(
        "/World/Geometry/Crates/Crate_01"
    )
    assert details["/World/Geometry/Crates/Crate_01"].instance_path is None
    # Instanceable metadata without composition arcs leaves a prim no instance.
    instanceable = details["/World/Geometry/Crates/Crate_Instanceable"]
    assert instanceable.is_instanceable
    assert not instanceable.is_instance
    assert details["/World/Geometry/Prop_Payloaded"].has_payload
    assert details["/World/Geometry/Prop_Variants"].has_variants
    assert details["/World/Geometry/Crates/Crate_Unique"].has_references
    assert not details["/World/Geometry/Disabled"].is_active
    assert details["/World/Sun"].display_name == "Key Light"  # as the fixture authors it
    assert details["/World/Geometry"].display_name == ""
    assert details["/World"].model_kind == "assembly"  # as the fixture authors them
    assert details["/World/Geometry/Crates/Crate_01"].model_kind == "component"
    assert details["/World/Geometry/Crates/Crate_01/Lid"].model_kind == "subcomponent"  # from the class
    assert details["/World/Camera"].model_kind == ""
    # Red is a component under a Scope with no kind; the Crates' ancestors are groups and an assembly
    assert [path for path, d in details.items() if d.is_invalid_model] == ["/World/Looks/Red"]
    tree.toggle(world, recursive=True)
    assert _paths(tree) == TOP_LEVEL
    tree.toggle(world)  # the recursive collapse collapsed the descendants too
    assert _paths(tree) == ["/_Crate", "/World", *WORLD_CHILDREN, "/World_Override_Only"]


def test_classes_and_orphaned_overs_are_rows(stage: Usd.Stage) -> None:
    tree = PrimTree(stage)
    details = [tree.details(row) for row in tree.rows]  # /_Crate, /World, /World_Override_Only
    assert [d.is_class for d in details] == [True, False, False]
    assert [d.is_orphaned_over for d in details] == [False, False, True]
    assert [d.has_children for d in details] == [True, True, True]


def test_an_unloaded_payloads_contents_are_neither_rows_nor_search_matches(stage: Usd.Stage) -> None:
    unloaded = Sdf.Path("/World/Geometry/Prop_Unloaded")
    contents = ["/World/Geometry/Prop_Unloaded/Body", "/World/Geometry/Prop_Unloaded/Lid"]  # the class's children
    tree = PrimTree(stage)
    row_index = tree.reveal(unloaded)
    assert row_index is not None
    tree.toggle(row_index)
    assert [path for path in _paths(tree) if path.startswith(f"{unloaded}/")] == contents  # loaded, as it opens
    stage.Unload(unloaded)
    tree.refresh()
    assert not any(path.startswith(f"{unloaded}/") for path in _paths(tree))
    details = tree.details(tree.rows[_index(tree, str(unloaded))])
    assert details.has_payload
    assert not details.is_loaded
    assert not details.has_children  # so the row draws no disclosure triangle
    lids = prim_search.search(stage, prim_search.SearchQuery(text="lid"), match_limit=100).matching_paths
    assert Sdf.Path(f"{unloaded}/Lid") not in lids
    assert Sdf.Path("/World/Geometry/Prop_Payloaded/Lid") in lids  # still loaded


def test_child_count_counts_what_the_tree_lists(stage: Usd.Stage) -> None:
    assert prim_search.child_count(stage.GetPrimAtPath("/World")) == len(WORLD_CHILDREN)
    assert prim_search.child_count(stage.GetPrimAtPath("/World/Camera")) == 0
    # An instance's children are instance proxies, Body and Lid from the prototype, as its expanded row lists them.
    assert prim_search.child_count(stage.GetPrimAtPath("/World/Geometry/Crates/Crate_01")) == 2
    tree = PrimTree(stage)
    world = tree.details(tree.rows[_index(tree, "/World")])
    assert world.child_count == len(WORLD_CHILDREN)
    assert world.has_children


def test_keys_expand_then_step_in_and_collapse_then_step_out(stage: Usd.Stage) -> None:
    tree = PrimTree(stage)
    world = _index(tree, "/World")
    assert tree.expand_or_enter_row(world) == world
    assert tree.is_expanded(tree.rows[world])
    geometry = tree.expand_or_enter_row(world)
    assert _paths(tree)[geometry] == "/World/Geometry"
    assert tree.collapse_or_select_parent(geometry) == world  # Geometry is collapsed, so Left goes to its parent
    assert tree.collapse_or_select_parent(world) == world
    assert not tree.is_expanded(tree.rows[world])
    override_only = _index(tree, "/World_Override_Only")
    assert tree.collapse_or_select_parent(override_only) == override_only  # no parent row to go to
    camera_row = tree.reveal(Sdf.Path("/World/Camera"))
    assert camera_row is not None
    assert tree.expand_or_enter_row(camera_row) == camera_row  # a leaf neither expands nor steps


def test_reveal_expands_every_ancestor(stage: Usd.Stage) -> None:
    tree = PrimTree(stage)
    panel = tree.reveal(Sdf.Path("/World/Geometry/Crates/Crate_02/Lid/Panel"))
    assert panel is not None
    assert _paths(tree)[panel] == "/World/Geometry/Crates/Crate_02/Lid/Panel"
    assert tree.rows[panel].depth == 5
    assert tree.reveal(Sdf.Path("/World/Nowhere")) is None


def test_refresh_reads_added_and_removed_prims_and_keeps_expansion(stage: Usd.Stage) -> None:
    tree = PrimTree(stage)
    tree.reveal(Sdf.Path("/World/Looks/Red"))
    stage.DefinePrim("/World/Added", "Xform")
    stage.RemovePrim("/World/Looks/Red")  # authored in the root layer, so it goes
    tree.refresh()
    assert "/World/Added" in _paths(tree)
    assert "/World/Looks/Red" not in _paths(tree)
    assert tree.is_expanded(tree.rows[_index(tree, "/World/Looks")])
    assert Sdf.Path("/World/Looks/Red") not in tree.expanded_paths


def test_a_refresh_under_a_search_drops_removed_prims_from_the_expansion_it_restores(stage: Usd.Stage) -> None:
    tree = PrimTree(stage)
    tree.reveal(Sdf.Path("/World/Looks/Red"))  # expands /World and /World/Looks
    tree.set_search(prim_search.search(stage, prim_search.SearchQuery(text="sun"), match_limit=100))
    stage.RemovePrim("/World/Looks")
    tree.refresh()
    tree.set_search(None)  # restores the expansion from before the search
    stage.DefinePrim("/World/Looks/Red")  # the same paths again, new prims
    tree.refresh()
    assert not tree.is_expanded(tree.rows[_index(tree, "/World/Looks")])


def test_a_tree_never_keeps_its_stage_alive(tmp_path: Path) -> None:
    # Opened here, not by the fixture, which pytest holds until the test ends.
    stage = open_stage_without_cache(copy_scene(Scene.SCENE_GRAPH, tmp_path) / "prim_kinds.usda")
    tree = PrimTree(stage)
    assert tree.stage() == stage
    del stage
    gc.collect()
    assert tree.is_expired()
    assert tree.stage() is None
