"""The temporary UI's cook inspector: the last cook's Viewer stage in the scene graph and property viewer widgets.

The widgets' own tests cover what they draw; these cover what the inspector hosts. Each test cooks a tree built through
bpy as a user would, then reads the views, and the header draws into a recording layout
(support/recording_layout.py). The view's callbacks are called as the widgets call them.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import bpy
from pxr import Sdf

from proscenium.interface import cook_inspector, cook_node_types, cook_panel
from proscenium_ui.property_viewer_widget import display as property_display
from proscenium_ui.property_viewer_widget.display import property_viewer_views
from proscenium_ui.scene_graph_widget import display
from proscenium_ui.scene_graph_widget.display import scene_graph_views
from support.recording_layout import RecordingLayout

if TYPE_CHECKING:
    from types import ModuleType

CHAIR = Sdf.Path("/Chair")


def _tree(name: str = "Tree") -> Any:
    node_groups: Any = bpy.data.node_groups  # the stubs list only Blender's own tree types
    return node_groups.new(name, cook_node_types.TREE_IDNAME)


def _node(tree: Any, type_name: str, name: str) -> Any:
    node = tree.nodes.new(f"ProsceniumCook{type_name}")
    node.name = name
    return node


def _viewer_tree() -> Any:
    """Begin -> Create Prim (/Chair, an Xform) -> End -> Viewer, the tree's chosen Viewer."""
    tree = _tree()
    begin = _node(tree, "NewLayerZoneBegin", "Begin")
    create = _node(tree, "CreatePrim", "Create Prim")
    end = _node(tree, "NewLayerZoneEnd", "End")
    viewer = _node(tree, "Viewer", "Viewer")
    begin.zone_end = "End"
    create.inputs["Name"].default_value = "Chair"
    create.prop_type = "Xform"  # so the Chair has Xform's visibility attribute
    tree.links.new(begin.outputs["Layer"], create.inputs["Editable Layer"])
    tree.links.new(create.outputs["Editable Layer"], end.inputs["Layer"])
    tree.links.new(end.outputs["Layer"], viewer.inputs["Layer"])
    tree.viewer = "Viewer"
    return tree


def _header(tree: Any) -> tuple[bool, list[str]]:
    layout = RecordingLayout()
    draws_tree = cook_inspector.draw_viewer_header(layout, tree)
    return draws_tree, [text for text, _icon, _enabled in layout.labels]


def _shown_prim() -> Sdf.Path | None:
    return property_viewer_views.property_viewer_view(cook_inspector.PROPERTY_VIEW_NAME).property_list_view.prim_path


def _shows(stage: Any) -> bool:
    tree = scene_graph_views.scene_graph_view(cook_inspector.VIEW_NAME).prim_tree_view.live_tree()
    return tree is not None and tree.is_on_stage(stage)


def test_a_cook_shows_its_viewer_stage(extension: ModuleType) -> None:
    del extension
    tree = _viewer_tree()
    assert _header(tree) == (False, ["Cook to show the Viewer's stage"])
    stage = cook_panel.cook_tree(tree).viewer_stage
    assert stage is not None and _shows(stage)
    assert _header(tree) == (True, ["Viewer 'Viewer', as last cooked"])
    # A row's selection shows its prim's properties, as the widget's callback reports it.
    display.select_prim(cook_inspector.VIEW_NAME, CHAIR)
    cook_inspector.tree_selection_changed(display.selected_path(cook_inspector.VIEW_NAME))
    assert _shown_prim() == CHAIR


def test_a_cook_keeping_its_viewer_stage_keeps_the_selection(extension: ModuleType) -> None:
    del extension
    tree = _viewer_tree()
    first = cook_panel.cook_tree(tree).viewer_stage
    display.select_prim(cook_inspector.VIEW_NAME, CHAIR)
    cook_inspector.tree_selection_changed(CHAIR)
    second = cook_panel.cook_tree(tree).viewer_stage
    assert first == second  # the tree is unchanged, so the cook keeps its Viewer's stage
    assert display.selected_path(cook_inspector.VIEW_NAME) == CHAIR
    assert _shown_prim() == CHAIR


def test_the_header_says_why_no_stage_shows(extension: ModuleType) -> None:
    del extension
    tree = _viewer_tree()
    cook_panel.cook_tree(tree)
    other = _tree("Other")
    assert _header(other) == (False, ["Cook to show the Viewer's stage"])  # another tree's editor
    other.viewer = ""
    cook_panel.cook_tree(other)
    assert _header(other) == (False, ["The last cook had no Viewer"])
    assert _header(tree)[0] is False  # the views show the last cook's tree only
    tree.nodes.remove(tree.nodes["Viewer"])
    cook_panel.cook_tree(tree)
    assert _header(tree) == (False, ["Viewer 'Viewer' has no stage"])  # the cook warns unknown-viewer


def test_forgetting_the_cooks_shows_none(extension: ModuleType) -> None:
    del extension
    tree = _viewer_tree()
    cook_panel.cook_tree(tree)
    cook_panel.forget_cooks()  # as loading a file does
    assert not cook_inspector.shows_tree(tree)
    assert _header(tree) == (False, ["Cook to show the Viewer's stage"])


def test_jump_to_a_target_selects_its_prim_and_property(extension: ModuleType) -> None:
    del extension
    tree = _viewer_tree()
    cook_panel.cook_tree(tree)
    visibility = CHAIR.AppendProperty("visibility")
    cook_inspector.jump_to_target(visibility)
    assert display.selected_path(cook_inspector.VIEW_NAME) == CHAIR
    assert _shown_prim() == CHAIR
    assert property_display.selected_path(cook_inspector.PROPERTY_VIEW_NAME) == visibility


def test_views_show_in_the_node_editors_proscenium_tab(extension: ModuleType) -> None:
    del extension
    region = SimpleNamespace(type="UI", active_panel_category="Proscenium")
    assert cook_inspector.shows_in_region(SimpleNamespace(type="NODE_EDITOR"), region)
    assert not cook_inspector.shows_in_region(SimpleNamespace(type="VIEW_3D"), region)
