"""The property viewer widget's display (proscenium.ui.property_viewer_widget.display): views and rows.

Drawing needs a window, so nothing here draws: these check the RNA side a UIList draws from, on
scenes/property_viewer/property_kinds.usda.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest
from pxr import Sdf, Usd

from fixtures.scenes import Scene, copy_scene
from proscenium.ui.property_viewer_widget import display as property_display
from proscenium.ui.property_viewer_widget.display import (
    prim_summary,
    property_columns,
    property_viewer_operators,
    property_viewer_properties,
    property_viewer_registration,
    property_viewer_views,
)
from proscenium.ui.property_viewer_widget.property_list import PropertyRow
from proscenium.ui.scene_graph_widget import display
from proscenium.ui.widget_model import composition_arcs, prim_details
from proscenium.ui.widget_resources import badge_icons, keyframe_icons, theme_colors
from support.usd import open_stage_without_cache

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

BALL = Sdf.Path("/World/Ball")
BALL_AUTHORED_COUNT = 15  # of its 25 properties: a view shows only authored ones until that filter is off
INCLUDES = "collection:lights:includes"


class _ButtonProperties:
    """Stands in for an operator button's properties, which Blender passes to its description."""

    def __init__(self, view_name: str, row_index: int) -> None:
        self.view_name = view_name
        self.row_index = row_index


@pytest.fixture
def registered() -> Generator[None]:
    property_display.register()
    yield
    if property_display.is_registered():  # the reset also unregisters it if this didn't
        property_display.unregister()


@pytest.fixture
def stage(tmp_path: Path) -> Usd.Stage:
    return open_stage_without_cache(copy_scene(Scene.PROPERTY_VIEWER, tmp_path) / "property_kinds.usda")


def _never(_area: object, _region: object) -> bool:
    return False


def _properties(name: str) -> Any:
    properties = property_viewer_properties.view_properties(bpy.context.window_manager, name)
    assert properties is not None
    return properties


def _row_index(name: str, property_name: str) -> int:
    property_list = property_viewer_views.property_viewer_view(name).property_list_view.live_list()
    row_index = property_list.row_index(PropertyRow(property_name)) if property_list is not None else None
    assert row_index is not None
    return row_index


def _jump(row_index: int) -> set[str]:
    """Click the jump button on a row of the view named viewport."""
    return bpy.ops.proscenium.property_viewer_jump_to_target(view_name="viewport", row_index=row_index)  # ty: ignore[unresolved-attribute]


def _show_ball(name: str, stage: Usd.Stage) -> None:
    property_display.set_stage(name, stage)
    property_display.show_prim(name, BALL)


def test_registration_adds_only_a_popover_panel_and_unregistration_removes_everything(registered: None) -> None:
    panels = [cls for cls in property_viewer_registration.CLASSES if issubclass(cls, bpy.types.Panel)]
    assert [(panel.bl_space_type, panel.bl_region_type) for panel in panels] == [("TOPBAR", "HEADER")]
    property_display.create_view("viewport", _never)
    property_display.unregister()
    assert not hasattr(bpy.types.WindowManager, property_viewer_properties.VIEWS_PROPERTY)
    registered_classes: list[Any] = list(property_viewer_registration.CLASSES)
    assert not any(cls.is_registered for cls in registered_classes)
    with pytest.raises(property_display.ViewNotFoundError):
        property_display.selected_path("viewport")


def test_both_widgets_register_together_and_share_the_display(registered: None) -> None:
    display.register()
    display.unregister()  # the shared display stays registered for the property viewer
    assert bpy.ops.proscenium.copy_usd_path(usd_path="/World/Ball.radius") == {"FINISHED"}  # ty: ignore[unresolved-attribute]


def test_a_view_shows_a_prims_properties_as_rows(registered: None, stage: Usd.Stage) -> None:
    property_display.create_view("viewport", _never)
    assert len(_properties("viewport").rows) == 0
    _show_ball("viewport", stage)
    assert len(_properties("viewport").rows) == BALL_AUTHORED_COUNT
    property_display.show_prim("viewport", None)
    assert len(_properties("viewport").rows) == 0
    with pytest.raises(ValueError, match="exists"):
        property_display.create_view("viewport", _never)


def test_the_triangle_shows_a_relationships_targets(registered: None, stage: Usd.Stage) -> None:
    property_display.create_view("viewport", _never)
    _show_ball("viewport", stage)
    includes_row = _row_index("viewport", INCLUDES)
    toggle = property_viewer_operators.PropertyViewerToggleRow
    assert toggle.description(bpy.context, _ButtonProperties("viewport", includes_row)).startswith(
        f"Show the targets of {INCLUDES}."
    )
    assert bpy.ops.proscenium.property_viewer_toggle_row(view_name="viewport", row_index=includes_row) == {"FINISHED"}  # ty: ignore[unresolved-attribute]
    assert len(_properties("viewport").rows) == BALL_AUTHORED_COUNT + 2
    assert toggle.description(bpy.context, _ButtonProperties("viewport", includes_row)).startswith("Hide")
    assert toggle.description(bpy.context, _ButtonProperties("nowhere", 0)) == ""


def test_the_active_row_selects_and_tells_the_host(registered: None, stage: Usd.Stage) -> None:
    selections: list[Sdf.Path | None] = []
    property_display.create_view("viewport", _never, selections.append)
    _show_ball("viewport", stage)
    _properties("viewport").active_row_index = _row_index("viewport", "radius")  # as a click does
    assert selections == [BALL.AppendProperty("radius")]
    assert property_display.selected_path("viewport") == BALL.AppendProperty("radius")
    stage.GetPrimAtPath("/World/Sun").CreateAttribute("radius", Sdf.ValueTypeNames.Double)
    property_viewer_properties.apply_stage_changes("viewport")
    property_display.show_prim("viewport", Sdf.Path("/World/Sun"))  # another prim with the property
    assert selections[-1] == Sdf.Path("/World/Sun.radius")
    assert _properties("viewport").active_row_index == _row_index("viewport", "radius")
    property_display.select_property("viewport", None)  # from elsewhere: the host isn't told
    assert selections[-1] == Sdf.Path("/World/Sun.radius")
    assert _properties("viewport").active_row_index == -1


def test_a_search_applies_from_the_fields(registered: None, stage: Usd.Stage) -> None:
    property_display.create_view("viewport", _never)
    _show_ball("viewport", stage)
    properties = _properties("viewport")
    assert properties.search_authored_only  # on by default
    properties.search_authored_only = False
    property_display.apply_pending("viewport")
    assert len(properties.rows) == 25
    properties.search_text = "xform"
    property_display.apply_pending("viewport")
    assert len(properties.rows) == 2


def test_the_row_tooltip_and_cells(registered: None, stage: Usd.Stage) -> None:
    property_display.create_view("viewport", _never)
    _show_ball("viewport", stage)
    properties = _properties("viewport")
    assert properties.rows[_row_index("viewport", "radius")].tooltip.startswith("/World/Ball.radius\ndouble")
    view = property_viewer_views.property_viewer_view("viewport")
    property_list = view.property_list_view.live_list()
    assert property_list is not None
    for name, icon in (("material:binding", "LINKED"), ("primvars:displayColor", "GROUP_VCOL"), ("radius", "DOT")):
        details = property_list.details(name)
        assert details is not None
        assert property_columns.row_icon(PropertyRow(name), details) == icon
    # Between its samples at 1, 2, and 3, Blender's animated color; at a sample, its keyed color.
    property_display.set_time_code("viewport", Usd.TimeCode(1.5))
    translate = property_list.details("xformOp:translate")
    assert translate is not None
    fill = property_columns.row_keyframe_fill(PropertyRow("xformOp:translate"), translate)
    assert fill is keyframe_icons.KeyframeFill.ANIMATED
    property_display.set_time_code("viewport", Usd.TimeCode(3))
    translate = property_list.details("xformOp:translate")
    assert translate is not None
    assert (
        property_columns.row_keyframe_fill(PropertyRow("xformOp:translate"), translate)
        is keyframe_icons.KeyframeFill.KEYED
    )
    radius = property_list.details("radius")
    assert radius is not None
    assert property_columns.row_keyframe_fill(PropertyRow("radius"), radius) is None


def test_keyframe_icons_are_outlined_diamonds_in_blenders_animated_colors(registered: None) -> None:
    colors = theme_colors.DEFAULT_THEME_COLORS
    for color in (colors.keyed_color, colors.animated_color):
        pixels = keyframe_icons._pixels(color, colors.keyframe_border_color)  # noqa: SLF001
        size = keyframe_icons.ICON_SIZE_PIXELS

        def pixel(column: int, row: int, pixels: list[float] = pixels, size: int = size) -> list[float]:
            start = 4 * (row * size + column)
            return pixels[start : start + 4]

        center = size // 2
        assert pixel(center, center) == pytest.approx([*color, 1.0])  # the fill, opaque
        assert pixel(0, 0)[3] == 0.0  # outside the diamond, clear
        # Walking out from the center along the middle row, the fill gives way to the border before the edge.
        edge = next(column for column in range(center, size) if pixel(column, center)[3] < 1.0) - 1
        assert pixel(edge, center)[:3] == pytest.approx(list(colors.keyframe_border_color[:3]), abs=0.05)
    assert keyframe_icons.icon_id(keyframe_icons.KeyframeFill.KEYED) is not None


def test_loading_a_file_makes_the_views_properties_again(registered: None, stage: Usd.Stage, tmp_path: Path) -> None:
    property_display.create_view("viewport", _never)
    _show_ball("viewport", stage)
    _properties("viewport").search_text = "radius"
    property_display.apply_pending("viewport")
    blend_path = tmp_path / "saved.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    properties = _properties("viewport")
    assert properties.search_text == "radius"
    assert len(properties.rows) == 1


def test_a_targets_jump_button_hands_its_path_to_the_host(registered: None, stage: Usd.Stage) -> None:
    jumps: list[Sdf.Path] = []
    property_display.create_view("viewport", _never, None, jumps.append)
    _show_ball("viewport", stage)
    for name in (INCLUDES, "missing"):
        bpy.ops.proscenium.property_viewer_toggle_row(view_name="viewport", row_index=_row_index("viewport", name))  # ty: ignore[unresolved-attribute]
    property_list = property_viewer_views.property_viewer_view("viewport").property_list_view.live_list()
    assert property_list is not None
    sun_row = property_list.row_index(PropertyRow(INCLUDES, Sdf.Path("/World/Sun")))
    nowhere_row = property_list.row_index(PropertyRow("missing", Sdf.Path("/World/Nowhere")))
    assert sun_row is not None
    assert nowhere_row is not None
    jump = property_viewer_operators.PropertyViewerJumpToTarget
    assert jump.description(bpy.context, _ButtonProperties("viewport", sun_row)) == "Select /World/Sun"
    assert _jump(sun_row) == {"FINISHED"}
    assert jumps == [Sdf.Path("/World/Sun")]
    # A missing target has nothing to select, and a property's own row no target.
    assert jump.description(bpy.context, _ButtonProperties("viewport", nowhere_row)).startswith("Nothing on the stage")
    assert _jump(nowhere_row) == {"CANCELLED"}
    radius_row = _row_index("viewport", "radius")
    assert _jump(radius_row) == {"CANCELLED"}
    assert jumps == [Sdf.Path("/World/Sun")]


def test_without_a_jump_callback_a_jump_does_nothing(registered: None, stage: Usd.Stage) -> None:
    property_display.create_view("viewport", _never)
    _show_ball("viewport", stage)
    bpy.ops.proscenium.property_viewer_toggle_row(view_name="viewport", row_index=_row_index("viewport", INCLUDES))  # ty: ignore[unresolved-attribute]
    target_row = _row_index("viewport", INCLUDES) + 1
    assert _jump(target_row) == {"CANCELLED"}


def test_the_summary_lists_a_prims_facts_and_its_arcs_with_their_badges(registered: None, tmp_path: Path) -> None:
    # On the scene graph's own scene, whose prims have arcs and kinds: Crate_Unique inherits and references /_Crate.
    stage = open_stage_without_cache(copy_scene(Scene.SCENE_GRAPH, tmp_path) / "prim_kinds.usda")
    property_display.create_view("viewport", _never)
    property_display.set_stage("viewport", stage)
    property_display.show_prim("viewport", Sdf.Path("/World/Geometry/Crates/Crate_Unique"))
    view = property_viewer_views.property_viewer_view("viewport")
    property_list = view.property_list_view.live_list()
    assert property_list is not None
    lines = prim_summary.view_summary_lines(view, property_list)
    arcs = composition_arcs.CompositionArc
    assert lines == [
        prim_summary.SummaryLine("/World/Geometry/Crates/Crate_Unique"),
        prim_summary.SummaryLine("Type: Xform   Spec: Def   Kind: component"),
        prim_summary.SummaryLine("Inherits: /_Crate", badge_icons.ARC_LOOKS[arcs.INHERITS]),
        prim_summary.SummaryLine("References: /_Crate", badge_icons.ARC_LOOKS[arcs.REFERENCES]),
    ]
    assert prim_summary.view_summary_lines(view, property_list) is lines  # read once per list
    stage.GetPrimAtPath("/World/Geometry/Crates/Crate_Unique").SetActive(False)
    property_viewer_properties.apply_stage_changes("viewport")  # a new list, so the summary is read again
    property_list = view.property_list_view.live_list()
    assert property_list is not None
    assert prim_summary.SummaryLine("Inactive") in prim_summary.view_summary_lines(view, property_list)


def test_the_summary_greys_a_badge_whose_arc_isnt_in_effect(registered: None, tmp_path: Path) -> None:
    # An unloaded payload's badge greys out, as the scene graph's does; an instance's badge leads its line.
    stage = open_stage_without_cache(copy_scene(Scene.SCENE_GRAPH, tmp_path) / "prim_kinds.usda")
    stage.Unload(Sdf.Path("/World/Geometry/Prop_Unloaded"))
    unloaded = prim_summary.summary_lines(*_prim_details(stage, "/World/Geometry/Prop_Unloaded"))
    payload = badge_icons.ARC_LOOKS[composition_arcs.CompositionArc.PAYLOAD]
    assert prim_summary.SummaryLine("Payload (unloaded): /_Crate", payload, is_in_effect=False) in unloaded
    instance = prim_summary.summary_lines(*_prim_details(stage, "/World/Geometry/Crates/Crate_01"))
    assert [line.badge_look for line in instance if line.badge_look is not None][0] == badge_icons.INSTANCE_BADGE_LOOK
    assert "Type: Xform   Spec: Def   Kind: component" in [line.text for line in instance]


def _prim_details(stage: Usd.Stage, path: str) -> tuple[Any, Any]:
    prim = stage.GetPrimAtPath(path)
    return prim_details.row_details_of(prim), prim_details.prim_details_of(prim)
