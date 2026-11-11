"""A prim tree as a widget shows it, and what it says about prims (proscenium.ui.scene_graph_widget.prim_tree).

On scenes/scene_graph/prim_kinds.usda; expected values are written from how the scene is built.
"""

from __future__ import annotations

import gc
from typing import TYPE_CHECKING

import pytest
from pxr import Sdf, Usd

from fixtures.scenes import Scene, copy_scene
from proscenium.ui.scene_graph_widget.prim_tree import PrimTreeView, StepDirection, prim_descriptions, prim_search
from proscenium.ui.scene_graph_widget.prim_tree.prim_tree_view import PendingChange, SearchStatus
from support.usd import open_stage_without_cache

if TYPE_CHECKING:
    from pathlib import Path

INTO = StepDirection.INTO
OUT_OF = StepDirection.OUT_OF


@pytest.fixture
def stage(tmp_path: Path) -> Usd.Stage:
    return open_stage_without_cache(copy_scene(Scene.SCENE_GRAPH, tmp_path) / "prim_kinds.usda")


def _view(stage: Usd.Stage, changes: list[None] | None = None) -> PrimTreeView:
    view = PrimTreeView(None if changes is None else lambda: changes.append(None))
    view.set_stage(stage)
    return view


def _selected(view: PrimTreeView) -> str:
    return str(view.selected_path)


def test_steps_move_the_selection(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.select_path(Sdf.Path("/World"))
    assert view.step(INTO, recursive=False) == view.active_row_index()  # expands World, stays on it
    assert _selected(view) == "/World"
    view.step(INTO, recursive=False)
    assert _selected(view) == "/World/Geometry"
    view.step(OUT_OF, recursive=False)
    assert _selected(view) == "/World"
    view.step(INTO, recursive=True)  # Shift+Right expands the whole subtree, staying on the row
    assert _selected(view) == "/World"
    assert view.tree is not None
    assert len(view.tree.rows) == 31


def test_a_step_with_nothing_selected_starts_at_the_first_row(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.step(INTO, recursive=False)
    assert _selected(view) == "/_Crate"


def test_showing_the_same_stage_again_keeps_its_state(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.select_path(Sdf.Path("/World/Looks/Red"))
    view.set_stage(stage)
    assert _selected(view) == "/World/Looks/Red"
    view.set_stage(None)
    assert view.tree is None
    assert view.selected_path is None


def test_a_query_filters_and_clearing_it_reveals_the_selection(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.set_query(prim_search.SearchQuery(text="panel"))
    assert view.search_status.text.startswith("5 matches")
    view.select_path(Sdf.Path("/World/Geometry/Crates/Crate_02/Lid/Panel"))
    view.set_query(prim_search.SearchQuery())
    assert view.search_status == SearchStatus()
    assert view.active_row_index() is not None
    view.set_query(prim_search.SearchQuery(text="(", mode=prim_search.SearchMode.REGEX))
    assert view.search_status.is_error


def test_a_query_set_before_a_stage_applies_to_it(stage: Usd.Stage) -> None:
    view = PrimTreeView()
    view.set_query(prim_search.SearchQuery(text="sun"))
    view.set_stage(stage)
    assert view.tree is not None
    assert [str(row.path) for row in view.tree.rows] == ["/World", "/World/Sun"]


def test_stage_changes_are_marked_and_read_once_the_edit_is_over(stage: Usd.Stage) -> None:
    changes: list[None] = []
    view = _view(stage, changes)
    view.select_path(Sdf.Path("/World/Camera"))
    stage.GetPrimAtPath("/World/Camera").CreateAttribute("focalLength", Sdf.ValueTypeNames.Float).Set(50.0)
    assert view.pending_change is PendingChange.NONE  # a property value shows in no row
    stage.GetPrimAtPath("/World/Camera").SetMetadata("comment", "metadata only")
    assert view.pending_change is PendingChange.DETAILS
    stage.DefinePrim("/World/Added")
    stage.DefinePrim("/World/AddedToo")
    assert view.pending_change is PendingChange.HIERARCHY
    assert len(changes) == 1  # told once, until the change is read
    assert view.apply_pending_changes()
    assert view.tree is not None
    assert "/World/AddedToo" in [str(row.path) for row in view.tree.rows]
    assert not view.apply_pending_changes()


def test_a_selected_prim_leaving_the_stage_is_deselected(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.select_path(Sdf.Path("/World/Sun"))
    stage.RemovePrim("/World/Sun")
    view.apply_pending_changes()
    assert view.selected_path is None
    view.select_path(Sdf.Path("/World/Looks/Red/Surface"))
    stage.GetPrimAtPath("/World/Looks").SetActive(False)  # an inactive prim stays, but its children aren't composed
    view.apply_pending_changes()
    assert view.selected_path is None
    view.select_path(Sdf.Path("/World/NoSuchPrim"))
    assert view.selected_path is None


def test_a_hidden_selection_stays(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.select_path(Sdf.Path("/World/Sun"))
    world_row = view.tree.row_index(Sdf.Path("/World")) if view.tree is not None else None
    assert world_row is not None
    view.toggle_row(world_row)  # collapsed out of sight
    view.set_query(prim_search.SearchQuery(text="lid"))  # filtered out of sight
    stage.DefinePrim("/World/Added")
    view.apply_pending_changes()
    assert view.active_row_index() is None
    assert view.selected_path == Sdf.Path("/World/Sun")


def test_a_change_reruns_the_query(stage: Usd.Stage) -> None:
    view = _view(stage)
    view.set_query(prim_search.SearchQuery(text="sun"))
    stage.DefinePrim("/World/Looks/Sunset")
    view.apply_pending_changes()
    assert view.tree is not None
    assert view.search_status.text.startswith("2 matches")


def test_a_released_stage_leaves_an_expired_view(tmp_path: Path) -> None:
    # Opened here, not by the fixture, which pytest holds until the test ends; the listener doesn't hold it either.
    stage = open_stage_without_cache(copy_scene(Scene.SCENE_GRAPH, tmp_path) / "prim_kinds.usda")
    view = _view(stage)
    del stage
    gc.collect()
    assert view.live_tree() is None
    assert view.step(INTO, recursive=False) is None


def test_badges_and_tooltips(stage: Usd.Stage) -> None:
    view = _view(stage)
    assert view.tree is not None
    crate_row = view.tree.rows[view.select_path(Sdf.Path("/World/Geometry/Crates/Crate_01")) or 0]
    badges = prim_descriptions.row_badges(view.tree.details(crate_row))
    assert badges == [prim_descriptions.Badge.REFERENCES, prim_descriptions.Badge.INSTANCE]
    crate = stage.GetPrimAtPath("/World/Geometry/Crates/Crate_01")
    assert prim_descriptions.row_tooltip(crate) == "/World/Geometry/Crates/Crate_01\nXform, Def\nKind: component"
    assert prim_descriptions.badge_tooltip(crate, prim_descriptions.Badge.REFERENCES) == "References: /_Crate"
    assert prim_descriptions.badge_tooltip(crate, prim_descriptions.Badge.INSTANCE).startswith("Instance of prototype ")
    body = stage.GetPrimAtPath("/World/Geometry/Crates/Crate_01/Body")
    assert prim_descriptions.badge_tooltip(body, prim_descriptions.Badge.INSTANCE).startswith("Inside an instance")
    payloaded = stage.GetPrimAtPath("/World/Geometry/Prop_Payloaded")
    assert prim_descriptions.badge_tooltip(payloaded, prim_descriptions.Badge.PAYLOAD) == "Payload (loaded): /_Crate"
    variants = stage.GetPrimAtPath("/World/Geometry/Prop_Variants")
    assert prim_descriptions.badge_tooltip(variants, prim_descriptions.Badge.VARIANTS) == "Variants: shape = box"
    assert prim_descriptions.disclosure_tooltip(crate, is_expanded=False).startswith("Expand Crate_01.")
    assert prim_descriptions.details_lines(crate)[0] == "/World/Geometry/Crates/Crate_01"
