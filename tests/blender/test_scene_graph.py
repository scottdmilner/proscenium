"""The scene graph widget's display (proscenium.ui.scene_graph_widget.display): registration, views, and rows.

Drawing needs a window, so nothing here draws: these check the RNA side a UIList draws from, on
scenes/scene_graph/prim_kinds.usda, whose top level is _Crate, World, and World_Override_Only.
"""

from __future__ import annotations

import dataclasses
import gc
from typing import TYPE_CHECKING, Any

import bpy
import pytest
from pxr import Sdf, Usd

from fixtures.scenes import Scene, copy_scene
from proscenium.ui.scene_graph_widget import display
from proscenium.ui.scene_graph_widget.display import (
    badge_icons,
    tinted_icons,
    widget_colors,
    widget_operators,
    widget_properties,
    widget_registration,
    widget_views,
)
from proscenium.ui.scene_graph_widget.display.list_columns import name_column
from support.usd import open_stage_without_cache

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

WORLD_ROW = 1


class _ButtonProperties:
    """Stands in for an operator button's properties, which Blender passes to its description."""

    def __init__(self, view_name: str, row_index: int) -> None:
        self.view_name = view_name
        self.row_index = row_index


@pytest.fixture
def registered() -> Generator[None]:
    display.register()
    yield
    if display.is_registered():  # the reset also unregisters it if this didn't
        display.unregister()


@pytest.fixture
def stage(tmp_path: Path) -> Usd.Stage:
    return open_stage_without_cache(copy_scene(Scene.SCENE_GRAPH, tmp_path) / "prim_kinds.usda")


def _properties(name: str) -> Any:
    properties = widget_properties.view_properties(bpy.context.window_manager, name)
    assert properties is not None
    return properties


def _never(_area: object, _region: object) -> bool:
    return False


def test_registration_adds_only_a_popover_panel_and_unregistration_removes_everything(registered: None) -> None:
    # A header panel shows only where a popover opens it, so the widget shows nowhere by itself.
    panels = [cls for cls in widget_registration.CLASSES if issubclass(cls, bpy.types.Panel)]
    assert [(panel.bl_space_type, panel.bl_region_type) for panel in panels] == [("TOPBAR", "HEADER")]
    assert hasattr(bpy.types.WindowManager, widget_properties.VIEWS_PROPERTY)
    display.create_view("viewport", _never)
    display.unregister()
    assert not hasattr(bpy.types.WindowManager, widget_properties.VIEWS_PROPERTY)
    registered_classes: list[Any] = list(widget_registration.CLASSES)  # is_registered is Blender's, not stubbed
    assert not any(cls.is_registered for cls in registered_classes)
    with pytest.raises(display.ViewNotFoundError):
        display.selected_path("viewport")


def test_views_keep_separate_rows(registered: None, stage: Usd.Stage) -> None:
    display.create_view("viewport", _never)
    display.create_view("node_editor", _never)
    display.set_stage("viewport", stage)
    display.set_stage("node_editor", stage)
    assert bpy.ops.proscenium.scene_graph_toggle_row(view_name="viewport", row_index=WORLD_ROW) == {"FINISHED"}  # ty: ignore[unresolved-attribute]
    assert len(_properties("viewport").rows) == 8  # World's five children spliced in
    assert len(_properties("node_editor").rows) == 3
    with pytest.raises(ValueError, match="exists"):
        display.create_view("viewport", _never)
    display.remove_view("node_editor")
    assert widget_properties.view_properties(bpy.context.window_manager, "node_editor") is None


def test_a_recursive_toggle_and_the_triangle_tooltip(registered: None, stage: Usd.Stage) -> None:
    display.create_view("viewport", _never)
    display.set_stage("viewport", stage)
    toggle = widget_operators.SceneGraphToggleRow
    assert toggle.description(bpy.context, _ButtonProperties("viewport", WORLD_ROW)).startswith("Expand World.")
    bpy.ops.proscenium.scene_graph_toggle_row(view_name="viewport", row_index=WORLD_ROW, recursive=True)  # ty: ignore[unresolved-attribute]
    assert len(_properties("viewport").rows) == 36
    assert toggle.description(bpy.context, _ButtonProperties("viewport", WORLD_ROW)).startswith("Collapse World.")
    assert toggle.description(bpy.context, _ButtonProperties("nowhere", 0)) == ""


def test_the_copy_path_button_names_its_prim(registered: None) -> None:
    # The background wheel has no clipboard to read back, so this checks the button's tooltip and that it runs.
    class _CopyButtonProperties:
        prim_path = "/World/Camera"

    assert widget_operators.SceneGraphCopyPath.description(bpy.context, _CopyButtonProperties()) == "Copy /World/Camera"
    assert bpy.ops.proscenium.scene_graph_copy_path(prim_path="/World/Camera") == {"FINISHED"}  # ty: ignore[unresolved-attribute]


def test_the_active_row_selects_and_tells_the_host(registered: None, stage: Usd.Stage) -> None:
    selections: list[Sdf.Path | None] = []
    display.create_view("viewport", _never, selections.append)
    display.set_stage("viewport", stage)
    assert selections == []  # showing a stage selects nothing
    _properties("viewport").active_row_index = WORLD_ROW  # as a click or the list's Up and Down keys do
    assert selections == [Sdf.Path("/World")]
    display.select_prim("viewport", Sdf.Path("/World/Looks/Red/Surface"))  # from elsewhere: the host isn't told
    assert selections == [Sdf.Path("/World")]
    properties = _properties("viewport")
    assert properties.active_row_index == 5  # after /_Crate, /World, /World/Geometry, /World/Looks, and Red
    assert properties.rows[properties.active_row_index].tooltip == "/World/Looks/Red/Surface\nShader, Def"


def test_a_rows_tooltip_says_what_its_badges_mark(registered: None, stage: Usd.Stage) -> None:
    display.create_view("viewport", _never)
    display.set_stage("viewport", stage)
    display.select_prim("viewport", Sdf.Path("/World/Geometry/Prop_Payloaded"))
    properties = _properties("viewport")
    tooltip = properties.rows[properties.active_row_index].tooltip
    assert tooltip.endswith("\nPayload (loaded): /_Crate\nSpecializes: /_Crate")


def test_search_fields_filter_the_rows(registered: None, stage: Usd.Stage) -> None:
    display.create_view("viewport", _never)
    display.set_stage("viewport", stage)
    properties = _properties("viewport")
    properties.search_text = "sun"
    display.apply_pending("viewport")  # as the search timer would, which needs an event loop
    assert len(properties.rows) == 2  # /World and /World/Sun
    properties.search_text = "prop_"
    display.apply_pending("viewport")
    view = widget_views.scene_graph_view("viewport").prim_tree_view
    assert view.tree is not None
    matching_paths = [str(row.path) for row in view.tree.rows if view.tree.is_match(row)]
    props = ["/World/Geometry/Prop_Payloaded", "/World/Geometry/Prop_Unloaded", "/World/Geometry/Prop_Variants"]
    assert matching_paths == props
    properties.search_shown_rows_only = True  # the props are under /World, which isn't expanded
    display.apply_pending("viewport")
    assert view.search_status.text.startswith("0 matches in shown rows")


def test_typing_a_search_leaves_the_arrow_keys_to_it_until_a_row_is_clicked(registered: None, stage: Usd.Stage) -> None:
    # The key watcher reads this, as it can't tell a text field is being edited.
    display.create_view("viewport", _never)
    display.set_stage("viewport", stage)
    properties = _properties("viewport")
    assert not widget_views.is_entering_search_text("viewport")
    properties.search_text = "w"  # as a keystroke in the box does
    assert widget_views.is_entering_search_text("viewport")
    properties.active_row_index = WORLD_ROW  # a click on a row
    assert not widget_views.is_entering_search_text("viewport")
    properties.search_text = "wo"
    bpy.ops.proscenium.scene_graph_toggle_row(view_name="viewport", row_index=WORLD_ROW)  # ty: ignore[unresolved-attribute]
    assert not widget_views.is_entering_search_text("viewport")  # a chevron is a click on a row too
    properties.search_text = "wor"
    widget_views.stop_entering_search_text()  # as Enter, Esc, or Tab does
    assert not widget_views.is_entering_search_text("viewport")


def test_stage_edits_reach_the_rows(registered: None, stage: Usd.Stage) -> None:
    display.create_view("viewport", _never)
    display.set_stage("viewport", stage)
    stage.DefinePrim("/Added")
    assert len(_properties("viewport").rows) == 3  # read once the edit is over, by a timer
    display.apply_pending("viewport")
    assert len(_properties("viewport").rows) == 4


def test_a_hovered_list_row_names_its_view(registered: None) -> None:
    # The key watcher reads context.property, over a row its list's active index, to pick among a region's views.
    display.create_view("first", _never)
    display.create_view("second", _never)
    wm = bpy.context.window_manager
    second_index = list(getattr(wm, widget_properties.VIEWS_PROPERTY).keys()).index("second")
    hovered = (wm, f"{widget_properties.VIEWS_PROPERTY}[{second_index}].active_row_index", -1)
    assert widget_properties.view_name_holding(hovered) == "second"
    assert widget_properties.view_name_holding(None) is None  # between the lists
    assert widget_properties.view_name_holding((wm, "clipboard", -1)) is None
    assert widget_properties.view_name_holding((bpy.context.scene, "frame_current", -1)) is None


def test_typing_a_search_doesnt_put_off_reading_a_stage_change(registered: None, stage: Usd.Stage) -> None:
    display.create_view("viewport", _never)
    display.set_stage("viewport", stage)
    view = widget_views.scene_graph_view("viewport")
    stage.DefinePrim("/Added")
    assert bpy.app.timers.is_registered(view.run_stage_changes)
    _properties("viewport").search_text = "sun"  # schedules the search, a pause later
    assert bpy.app.timers.is_registered(view.run_search)
    assert bpy.app.timers.is_registered(view.run_stage_changes)  # still due at once
    view.run_stage_changes()  # as its timer would
    assert len(_properties("viewport").rows) == 4  # the change is read; the search hasn't run
    assert view.prim_tree_view.query.is_empty()


def test_the_host_hears_its_selected_prim_leave_the_stage(registered: None, stage: Usd.Stage) -> None:
    selections: list[Sdf.Path | None] = []
    display.create_view("viewport", _never, selections.append)
    display.set_stage("viewport", stage)
    display.select_prim("viewport", Sdf.Path("/World/Sun"))
    stage.RemovePrim("/World/Sun")
    display.apply_pending("viewport")
    assert display.selected_path("viewport") is None
    assert selections == [None]
    assert _properties("viewport").active_row_index == -1


def test_the_host_hears_its_selection_go_when_the_stage_is_released(registered: None, tmp_path: Path) -> None:
    # Opened here, not by the fixture, which pytest holds until the test ends.
    released = open_stage_without_cache(copy_scene(Scene.SCENE_GRAPH, tmp_path) / "prim_kinds.usda")
    selections: list[Sdf.Path | None] = []
    display.create_view("viewport", _never, selections.append)
    display.set_stage("viewport", released)
    display.select_prim("viewport", Sdf.Path("/World/Sun"))
    del released
    gc.collect()
    assert display.selected_path("viewport") is None
    display.apply_pending("viewport")  # as the stage timer a draw of the closed stage schedules would
    assert selections == [None]


def test_a_file_load_ends_typing_a_search(registered: None, stage: Usd.Stage, tmp_path: Path) -> None:
    display.create_view("viewport", _never)
    display.set_stage("viewport", stage)
    _properties("viewport").search_text = "w"  # as a keystroke in the box does
    assert widget_views.is_entering_search_text("viewport")
    blend = tmp_path / "saved.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    assert not widget_views.is_entering_search_text("viewport")  # so the arrow keys step the tree again


def test_a_file_load_makes_the_properties_again(registered: None, stage: Usd.Stage, tmp_path: Path) -> None:
    display.create_view("viewport", _never)
    display.set_stage("viewport", stage)
    bpy.ops.proscenium.scene_graph_toggle_row(view_name="viewport", row_index=WORLD_ROW)  # ty: ignore[unresolved-attribute]
    blend = tmp_path / "saved.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    assert len(_properties("viewport").rows) == 8  # the view and its tree are the host's, and stay


def test_a_file_load_keeps_the_applied_search_and_a_pending_stage_change(
    registered: None, stage: Usd.Stage, tmp_path: Path
) -> None:
    display.create_view("viewport", _never)
    display.set_stage("viewport", stage)
    properties = _properties("viewport")
    properties.search_text = "sun*"
    properties.search_mode = "GLOB"
    display.apply_pending("viewport")
    assert len(properties.rows) == 2  # /World and /World/Sun
    stage.DefinePrim("/World/Sundial")  # marks a change the view's timer reads
    view = widget_views.scene_graph_view("viewport")
    blend = tmp_path / "saved.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    properties = _properties("viewport")
    assert (properties.search_text, properties.search_mode) == ("sun*", "GLOB")  # the fields show what's applied
    assert bpy.app.timers.is_registered(view.run_stage_changes)
    display.apply_pending("viewport")  # as the timer would
    assert view.prim_tree_view.query.text == "sun*"  # not cleared by the new, empty fields
    tree = view.prim_tree_view.tree
    assert tree is not None
    assert [str(row.path) for row in tree.rows] == ["/World", "/World/Sun", "/World/Sundial"]


def test_badge_shapes_are_kept_for_one_roundness(registered: None) -> None:
    # Dragging the theme's roundness draws the badges at many; only the last one's shapes are kept.
    shape_count = len(badge_icons.BADGE_LOOKS) * len(badge_icons.BadgePlace)
    for roundness in (0.1, 0.2, 0.3):
        theme_colors = dataclasses.replace(widget_colors.DEFAULT_THEME_COLORS, pie_menu_roundness=roundness)
        badge_icons._draw_icons(theme_colors)  # noqa: SLF001
    state = badge_icons._BadgeIconsState  # noqa: SLF001
    assert state.coverages_roundness == 0.3
    assert len(state.coverages_by_shape) <= shape_count
    badge_icons.remove_icons()
    assert not state.coverages_by_shape


def test_every_row_icon_has_a_mask_to_recolor(registered: None) -> None:
    # tools/row_icon_masks.py makes a mask for each icon a row can show; one missing would draw in the theme's color.
    for icon in name_column.row_icon_names():
        assert tinted_icons.icon_id(icon, (1.0, 0.5, 0.0)) is not None, icon
    assert tinted_icons.icon_id("NOT_A_ROW_ICON", (1.0, 0.5, 0.0)) is None
