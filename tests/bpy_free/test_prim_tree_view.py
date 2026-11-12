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

    from proscenium.ui.scene_graph_widget.prim_tree.prim_tree import RowDetails

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
    assert view.pending_change is PendingChange.PROPERTIES  # an added property shows in no row
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


def test_prim_details_are_read_again_after_a_property_is_added_but_not_after_a_value_changes(stage: Usd.Stage) -> None:
    view = _view(stage)
    assert view.tree is not None
    camera = Sdf.Path("/World/Camera")
    before = view.tree.prim_details(camera)
    assert before is not None
    assert view.tree.prim_details(camera) is before  # cached, so a redrawing panel doesn't read the prim again
    attribute = stage.GetPrimAtPath(camera).CreateAttribute("focalLength", Sdf.ValueTypeNames.Float)
    view.apply_pending_changes()
    after = view.tree.prim_details(camera)
    assert after is not None
    assert after.authored_attribute_count == before.authored_attribute_count + 1
    attribute.Set(50.0)
    assert view.pending_change is PendingChange.NONE  # a property value shows nowhere


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
    tree = view.tree

    def details(path: str) -> RowDetails:
        found = tree.details_at(Sdf.Path(path))
        assert found is not None, path
        return found

    def row_tooltip(path: str) -> str:
        prim_details = tree.prim_details(Sdf.Path(path))
        assert prim_details is not None, path
        return prim_descriptions.row_tooltip(details(path), prim_details)

    badge = prim_descriptions.Badge
    crate = "/World/Geometry/Crates/Crate_01"
    # One badge per arc authored on the prim, strongest first; an instance proxy's arcs are on its prototype's prims.
    badges_by_path = {
        crate: [badge.REFERENCES],
        "/World/Geometry/Crates/Crate_Unique": [badge.INHERITS, badge.REFERENCES],
        "/World/Geometry/Prop_Payloaded": [badge.PAYLOAD, badge.SPECIALIZES],
        "/World/Geometry/Prop_Variants": [badge.VARIANTS],
        f"{crate}/Body": [],
        "/World/Camera": [],
    }
    assert {path: prim_descriptions.row_badges(details(path)) for path in badges_by_path} == badges_by_path
    assert row_tooltip(crate) == f"{crate}\nXform, Def\nKind: component\nReferences: /_Crate"
    assert row_tooltip("/World/Looks/Red").endswith(
        "Kind: component\nNot a model: an ancestor isn't a group or assembly"
    )
    # The row's tooltip ends with a line per badge, in the badges' order.
    assert row_tooltip("/World/Geometry/Crates/Crate_Unique").endswith("\nInherits: /_Crate\nReferences: /_Crate")
    payloaded = row_tooltip("/World/Geometry/Prop_Payloaded")
    assert payloaded.endswith("\nPayload (loaded): /_Crate\nSpecializes: /_Crate")
    assert row_tooltip("/World/Geometry/Prop_Variants").endswith("\nVariants: shape = box")
    assert prim_descriptions.disclosure_tooltip(details(crate), is_expanded=False).startswith("Expand Crate_01.")
    crate_prim_details = tree.prim_details(Sdf.Path(crate))
    assert crate_prim_details is not None
    assert prim_descriptions.details_lines(details(crate), crate_prim_details)[0] == crate
    assert tree.details_at(Sdf.Path("/World/Nowhere")) is None
    assert tree.prim_details(Sdf.Path("/World/Nowhere")) is None


def test_an_unloaded_payload_and_an_unselected_variant_set_are_not_in_effect(stage: Usd.Stage) -> None:
    badge = prim_descriptions.Badge
    payloaded, variants = Sdf.Path("/World/Geometry/Prop_Payloaded"), Sdf.Path("/World/Geometry/Prop_Variants")
    view = _view(stage)
    assert view.tree is not None
    tree = view.tree

    def in_effect(path: Sdf.Path, shown: prim_descriptions.Badge) -> bool:
        details = tree.details_at(path)
        assert details is not None, path
        return prim_descriptions.is_badge_in_effect(details, shown)

    assert in_effect(payloaded, badge.PAYLOAD)  # loaded, as the stage opens
    assert in_effect(payloaded, badge.SPECIALIZES)  # only payloads and variants can be out of effect
    assert in_effect(variants, badge.VARIANTS)  # shape = box
    stage.Unload(payloaded)
    stage.GetPrimAtPath(variants).GetVariantSet("shape").ClearVariantSelection()
    tree.refresh()
    assert not in_effect(payloaded, badge.PAYLOAD)
    assert not in_effect(variants, badge.VARIANTS)
    prim_details = tree.prim_details(payloaded)
    assert prim_details is not None
    payload_details = tree.details_at(payloaded)
    assert payload_details is not None
    assert "\nPayload (unloaded): /_Crate" in prim_descriptions.row_tooltip(payload_details, prim_details)


def test_row_names_italicize_classes_and_fall_back_from_display_names(stage: Usd.Stage) -> None:
    view = _view(stage)
    assert view.tree is not None
    crate_class, world = (view.tree.details(row) for row in view.tree.rows[:2])
    assert prim_descriptions.row_name(crate_class, shows_display_name=False) == "_𝘊𝘳𝘢𝘵𝘦"  # sans-serif italic
    assert prim_descriptions.row_name(world, shows_display_name=True) == "World"  # no displayName: its name
    sun_row = view.tree.rows[view.select_path(Sdf.Path("/World/Sun")) or 0]
    sun = view.tree.details(sun_row)
    assert prim_descriptions.row_name(sun, shows_display_name=True) == "Key Light"
    assert prim_descriptions.row_name(sun, shows_display_name=False) == "Sun"
