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
from proscenium.ui.widget_model import composition_arcs, text_matching
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


def _row_index(view: PrimTreeView, path: str) -> int:
    row_index = view.tree.row_index(Sdf.Path(path)) if view.tree is not None else None
    assert row_index is not None
    return row_index


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
    assert len(view.tree.rows) == 36


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
    assert view.search_status.text.startswith("6 matches")  # each Lid's Panel
    view.select_path(Sdf.Path("/World/Geometry/Crates/Crate_02/Lid/Panel"))
    view.set_query(prim_search.SearchQuery())
    assert view.search_status == SearchStatus()
    assert view.active_row_index() is not None
    view.set_query(prim_search.SearchQuery(text="(", mode=text_matching.MatchMode.REGEX))
    assert view.search_status.is_error


def test_a_shown_rows_query_searches_only_the_rows_shown_and_expands_nothing(stage: Usd.Stage) -> None:
    view = _view(stage)
    assert view.tree is not None
    tree = view.tree
    view.select_path(Sdf.Path("/World/Geometry/Crates/Crate_01/Lid"))  # expands its ancestors, not the Lid
    shown_before = [str(row.path) for row in tree.rows]
    view.set_query(prim_search.SearchQuery(text="lid", shown_rows_only=True))
    assert view.search_status.text.startswith("1 matches in shown rows")
    # Crate_01's Lid is the one Lid shown: the class, the other crates, and the props are collapsed.
    assert [str(row.path) for row in tree.rows if tree.is_match(row)] == ["/World/Geometry/Crates/Crate_01/Lid"]
    assert set(str(row.path) for row in tree.rows) <= set(shown_before)  # nothing expanded to reach a match
    view.set_query(prim_search.SearchQuery(text="panel", shown_rows_only=True))
    assert view.search_status.text.startswith("0 matches")  # the Lid is collapsed, so its Panel isn't shown
    view.set_query(prim_search.SearchQuery(text="panel"))
    assert view.search_status.text.startswith("6 matches")  # the whole stage
    view.set_query(prim_search.SearchQuery())
    assert [str(row.path) for row in tree.rows] == shown_before  # the expansion from before the search


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


def test_selecting_a_prim_reads_the_pending_changes_first(stage: Usd.Stage) -> None:
    # Before the owner reads the changes: /World's row holds an expired prim, and /World/New's parent had no row.
    view = _view(stage)
    stage.RemovePrim("/World")
    stage.DefinePrim("/World/New/Child")
    assert view.pending_change is PendingChange.HIERARCHY
    row_index = view.select_path(Sdf.Path("/World/New/Child"))
    assert view.pending_change is PendingChange.NONE
    assert view.tree is not None
    assert row_index is not None
    assert str(view.tree.rows[row_index].path) == "/World/New/Child"
    assert not view.apply_pending_changes()  # the owner's read finds nothing left
    assert view.active_row_index() == row_index


def test_input_on_a_row_drawn_before_a_pending_change_finds_its_prim_after_it(stage: Usd.Stage) -> None:
    view = _view(stage)
    assert view.tree is not None
    view.toggle_row(_row_index(view, "/World"))
    drawn_paths = [str(row.path) for row in view.tree.rows]
    looks_row = drawn_paths.index("/World/Looks")
    stage.RemovePrim("/World/Geometry")  # before Looks, so its row moves up
    view.toggle_row(looks_row)
    assert view.tree.expanded_paths >= {Sdf.Path("/World"), Sdf.Path("/World/Looks")}
    assert view.pending_change is PendingChange.NONE
    stage.RemovePrim("/World/Camera")
    view.select_row(drawn_paths.index("/World/Sun"))
    assert _selected(view) == "/World/Sun"


def test_input_on_a_removed_prims_row_does_nothing(stage: Usd.Stage) -> None:
    view = _view(stage)
    world_row = view.select_path(Sdf.Path("/World"))
    assert world_row is not None
    stage.RemovePrim("/World")
    view.toggle_row(world_row)  # its row held an expired prim
    assert view.selected_path is None
    assert view.tree is not None
    assert "/World" not in [str(row.path) for row in view.tree.rows]
    assert not view.tree.expanded_paths
    view.select_path(Sdf.Path("/World_Override_Only"))
    stage.RemovePrim("/World_Override_Only")
    view.select_row(len(view.tree.rows) - 1)  # the last row drawn, now gone
    assert view.selected_path is None
    view.select_path(Sdf.Path("/_Crate/Lid"))
    stage.RemovePrim("/_Crate")
    view.step(INTO, recursive=False)  # from the first row, the selected one gone
    assert view.selected_path is None or view.tree.has_prim(view.selected_path)


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
    view.select_path(Sdf.Path("/World/Sun"))
    del stage
    gc.collect()
    assert view.live_tree() is None
    assert view.apply_pending_changes()  # no notice came; reading the changes drops the selection
    assert view.selected_path is None
    assert not view.apply_pending_changes()
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

    arc = composition_arcs.CompositionArc
    crate = "/World/Geometry/Crates/Crate_01"
    # Whether the instance badge shows, then one badge per arc authored on the prim, strongest first; an instance
    # proxy's arcs are on its prototype's prims.
    badges_by_path = {
        crate: (True, [arc.REFERENCES]),
        "/World/Geometry/Crates/Crate_Instanceable": (True, []),
        "/World/Geometry/Crates/Crate_Unique": (False, [arc.INHERITS, arc.REFERENCES]),
        "/World/Geometry/Prop_Payloaded": (False, [arc.PAYLOAD, arc.SPECIALIZES]),
        "/World/Geometry/Prop_Variants": (False, [arc.VARIANTS]),
        f"{crate}/Body": (False, []),
        "/World/Camera": (False, []),
    }
    shown_badges = {
        path: (prim_descriptions.has_instance_badge(details(path)), prim_descriptions.row_arcs(details(path)))
        for path in badges_by_path
    }
    assert shown_badges == badges_by_path
    crate_prim_details = tree.prim_details(Sdf.Path(crate))
    assert crate_prim_details is not None
    prototype = crate_prim_details.prototype_path
    assert row_tooltip(crate) == f"{crate}\nXform, Def\nKind: component\nInstance of {prototype}\nReferences: /_Crate"
    # Greyed out where the metadata does nothing; a proxy's tooltip names its instance.
    instanceable = details("/World/Geometry/Crates/Crate_Instanceable")
    assert not prim_descriptions.is_instance_badge_in_effect(instanceable)
    assert prim_descriptions.is_instance_badge_in_effect(details(crate))
    assert row_tooltip("/World/Geometry/Crates/Crate_Instanceable").endswith(
        "\nInstanceable, but not an instance: it has no composition arcs"
    )
    assert row_tooltip(f"{crate}/Body").endswith(f"\nInstance proxy, read-only: inside instance {crate}")
    assert row_tooltip("/World/Looks/Red").endswith(
        "Kind: component\nNot a model: an ancestor isn't a group or assembly"
    )
    # The row's tooltip ends with a line per badge, in the badges' order.
    assert row_tooltip("/World/Geometry/Crates/Crate_Unique").endswith("\nInherits: /_Crate\nReferences: /_Crate")
    payloaded = row_tooltip("/World/Geometry/Prop_Payloaded")
    assert payloaded.endswith("\nPayload (loaded): /_Crate\nSpecializes: /_Crate")
    assert row_tooltip("/World/Geometry/Prop_Variants").endswith("\nVariants: shape = box")
    assert prim_descriptions.disclosure_tooltip(details(crate), is_expanded=False).startswith("Expand Crate_01.")
    assert prim_descriptions.details_lines(details(crate), crate_prim_details)[0] == crate
    assert tree.details_at(Sdf.Path("/World/Nowhere")) is None
    assert tree.prim_details(Sdf.Path("/World/Nowhere")) is None


def test_an_inactive_instanceable_prim_says_why_it_isnt_an_instance(stage: Usd.Stage) -> None:
    # Deactivating an instance leaves its arcs, so its tooltip mustn't say it has none.
    view = _view(stage)
    crate = Sdf.Path("/World/Geometry/Crates/Crate_01")  # instanceable, and references /_Crate
    stage.GetPrimAtPath(crate).SetActive(False)
    view.apply_pending_changes()
    assert view.tree is not None
    details, prim_details = view.tree.details_at(crate), view.tree.prim_details(crate)
    assert details is not None
    assert prim_details is not None
    tooltip = prim_descriptions.row_tooltip(details, prim_details)
    assert "\nInstanceable, but not an instance: it's inactive" in tooltip
    assert "\nReferences: /_Crate" in tooltip


def test_arc_targets_are_the_composed_lists(stage: Usd.Stage) -> None:
    # A stronger layer's deletion or explicit list overrides a weaker one's, as composition does; a referenced
    # prim's own arcs are its layer stack's, which the referencing prim's layers can't edit.
    view = _view(stage)
    crate = Sdf.Path("/World/Geometry/Crates/Crate_Unique")  # references /_Crate in the root layer

    def references() -> tuple[str, ...]:
        view.apply_pending_changes()
        found = view.tree.prim_details(crate) if view.tree is not None else None
        assert found is not None
        return found.reference_targets

    with Usd.EditContext(stage, stage.GetSessionLayer()):
        stage.GetPrimAtPath(crate).GetReferences().AddInternalReference("/World/Looks")
        assert references() == ("/World/Looks", "/_Crate")  # prepended, in the stronger layer
        stage.GetPrimAtPath(crate).GetReferences().RemoveReference(Sdf.Reference(primPath="/_Crate"))
        assert references() == ("/World/Looks",)
        stage.GetPrimAtPath("/World/Looks").GetReferences().AddInternalReference("/World/Sun")
        stage.GetPrimAtPath(crate).GetReferences().RemoveReference(Sdf.Reference(primPath="/World/Sun"))
        assert references() == ("/World/Looks", "/World/Sun")  # /World/Looks's own reference stays
        stage.GetPrimAtPath(crate).GetReferences().SetReferences([])
        assert references() == ()


def test_an_unloaded_payload_and_an_unselected_variant_set_are_not_in_effect(stage: Usd.Stage) -> None:
    arc = composition_arcs.CompositionArc
    payloaded, variants = Sdf.Path("/World/Geometry/Prop_Payloaded"), Sdf.Path("/World/Geometry/Prop_Variants")
    view = _view(stage)
    assert view.tree is not None
    tree = view.tree

    def in_effect(path: Sdf.Path, shown: composition_arcs.CompositionArc) -> bool:
        details = tree.details_at(path)
        assert details is not None, path
        return prim_descriptions.is_arc_in_effect(details, shown)

    assert in_effect(payloaded, arc.PAYLOAD)  # loaded, as the stage opens
    assert in_effect(payloaded, arc.SPECIALIZES)  # only payloads and variants can be out of effect
    assert in_effect(variants, arc.VARIANTS)  # shape = box
    stage.Unload(payloaded)
    stage.GetPrimAtPath(variants).GetVariantSet("shape").ClearVariantSelection()
    tree.refresh()
    assert not in_effect(payloaded, arc.PAYLOAD)
    assert not in_effect(variants, arc.VARIANTS)
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
