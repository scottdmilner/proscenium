"""The scene graph widget's display (proscenium.ui.scene_graph_widget.display): registration, views, and rows.

Drawing needs a window, so nothing here draws: these check the RNA side a UIList draws from, on
scenes/scene_graph/prim_kinds.usda, whose top level is _Crate, World, and World_Override_Only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest
from pxr import Sdf, Usd

from fixtures.scenes import Scene, copy_scene
from proscenium.ui.scene_graph_widget import display
from proscenium.ui.scene_graph_widget.display import (
    widget_operators,
    widget_properties,
    widget_registration,
    widget_views,
)
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


def test_registration_adds_no_panel_and_unregistration_removes_everything(registered: None) -> None:
    assert not any(issubclass(cls, bpy.types.Panel) for cls in widget_registration.CLASSES)
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
    assert len(_properties("viewport").rows) == 35
    assert toggle.description(bpy.context, _ButtonProperties("viewport", WORLD_ROW)).startswith("Collapse World.")
    assert toggle.description(bpy.context, _ButtonProperties("nowhere", 0)) == ""


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
    properties.search_text = ""
    properties.search_payload = True
    display.apply_pending("viewport")
    view = widget_views.scene_graph_view("viewport").prim_tree_view
    assert view.tree is not None
    matching_paths = [str(row.path) for row in view.tree.rows if view.tree.is_match(row)]
    assert matching_paths == ["/World/Geometry/Prop_Payloaded", "/World/Geometry/Prop_Unloaded"]


def test_stage_edits_reach_the_rows(registered: None, stage: Usd.Stage) -> None:
    display.create_view("viewport", _never)
    display.set_stage("viewport", stage)
    stage.DefinePrim("/Added")
    assert len(_properties("viewport").rows) == 3  # read once the edit is over, by a timer
    display.apply_pending("viewport")
    assert len(_properties("viewport").rows) == 4


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
    assert bpy.app.timers.is_registered(view.run_pending)
    display.apply_pending("viewport")  # as the timer would
    assert view.prim_tree_view.query.text == "sun*"  # not cleared by the new, empty fields
    tree = view.prim_tree_view.tree
    assert tree is not None
    assert [str(row.path) for row in tree.rows] == ["/World", "/World/Sun", "/World/Sundial"]
