"""The cook inspector: the active Viewer's stage in the scene graph and property viewer widgets, in the node editor.

The panels sit below the Cook panel in the node editor's sidebar Proscenium tab. They show the Viewer stage of the last
cook, the cook panel giving each cook's stage to show_viewer_stage, while the edited tree is the one cooked; another
tree's editor says to cook it. Neither the views nor the inspector hold the stage: the tree's kept cook does
(cook_panel), so loading a file, which drops the kept cooks, releases it. A stage the cook keeps between cooks stays
shown with its expansion and selection, and the widgets follow its changes themselves.

As in the source inspector, the property viewer shows the prim the tree selects, and a target's jump button selects
its prim in the tree and its property in the property viewer. The Viewer's stage has no time samples the cook authors,
so the values shown are the default time code's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy

from proscenium_ui.property_viewer_widget import display as property_display
from proscenium_ui.scene_graph_widget import display

from . import cook_node_types

if TYPE_CHECKING:
    from pxr import Sdf, Usd

VIEW_NAME = "proscenium_cook_viewer"
PROPERTY_VIEW_NAME = "proscenium_cook_viewer_properties"
CATEGORY = "Proscenium"


class _Shown:
    """Which tree's last cook the views show, by its session UID, and that cook's Viewer; the stage isn't held."""

    tree_uid: int | None = None
    viewer: str | None = None
    has_stage = False


def show_viewer_stage(tree: bpy.types.NodeTree, viewer: str | None, stage: Usd.Stage | None) -> None:
    """Show a cook's Viewer stage, or none; the caller holds the stage while it's shown."""
    _Shown.tree_uid, _Shown.viewer, _Shown.has_stage = tree.session_uid, viewer, stage is not None
    property_display.set_stage(PROPERTY_VIEW_NAME, stage)
    display.set_stage(VIEW_NAME, stage)  # the stage already shown keeps its selection, which isn't reported again
    property_display.show_prim(PROPERTY_VIEW_NAME, display.selected_path(VIEW_NAME))


def forget_shown() -> None:
    """Show no tree's cook, as when the kept cooks are dropped."""
    _Shown.tree_uid, _Shown.viewer, _Shown.has_stage = None, None, False


def shows_tree(tree: bpy.types.NodeTree) -> bool:
    """Whether the views show a stage of this tree's last cook."""
    return _Shown.tree_uid == tree.session_uid and _Shown.has_stage


def tree_selection_changed(path: Sdf.Path | None) -> None:
    """The view's callback: show the selected prim's properties."""
    property_display.show_prim(PROPERTY_VIEW_NAME, path)


def jump_to_target(target_path: Sdf.Path) -> None:
    """The property viewer's callback: select a target's prim in the tree as a row click would, and its property."""
    display.select_prim(VIEW_NAME, target_path.GetPrimPath())  # not reported back, so told here
    tree_selection_changed(display.selected_path(VIEW_NAME))
    if target_path.IsPropertyPath():
        property_display.select_property(PROPERTY_VIEW_NAME, target_path.name)


def shows_in_region(area: Any, region: Any) -> bool:
    """Whether a region draws the views now: a node editor's sidebar on the Proscenium tab."""
    return area.type == "NODE_EDITOR" and region.type == "UI" and region.active_panel_category == CATEGORY


def draw_viewer_header(layout: Any, tree: bpy.types.NodeTree) -> bool:
    """Which Viewer's stage shows, or why none does; whether to draw the tree."""
    if _Shown.tree_uid != tree.session_uid:
        layout.label(text="Cook to show the Viewer's stage", icon="INFO")
        return False
    if _Shown.viewer is None:
        layout.label(text="The last cook had no Viewer", icon="INFO")
        return False
    if not _Shown.has_stage:
        layout.label(text=f"Viewer {_Shown.viewer!r} has no stage", icon="INFO")
        return False
    layout.label(text=f"Viewer {_Shown.viewer!r}, as last cooked", icon="HIDE_OFF")
    return True


def _edited_tree(context: Any) -> bpy.types.NodeTree | None:
    space: Any = context.space_data
    tree = getattr(space, "edit_tree", None)
    return tree if tree is not None and tree.bl_idname == cook_node_types.TREE_IDNAME else None


class _CookInspectorPanel:
    """What the inspector's panels share: the node editor's sidebar Proscenium tab, in a cook tree."""

    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = CATEGORY

    @classmethod
    def poll(cls, context: Any) -> bool:
        """Only in a node editor showing a cook tree."""
        return _edited_tree(context) is not None


class PROSCENIUM_PT_cook_viewer(_CookInspectorPanel, bpy.types.Panel):  # noqa: N801 - Blender's panel naming
    """The active Viewer's stage, as the last cook gave it."""

    bl_label = "Viewer Scene Graph"

    @override
    def draw(self, context: Any) -> None:
        tree = _edited_tree(context)
        assert tree is not None  # poll
        layout: Any = self.layout  # never None while drawing
        if draw_viewer_header(layout, tree):
            display.draw_tree(layout, context, VIEW_NAME)


class PROSCENIUM_PT_cook_viewer_properties(_CookInspectorPanel, bpy.types.Panel):  # noqa: N801 - Blender's naming
    """The properties of the prim the Viewer's scene graph selects."""

    bl_label = "Viewer Properties"

    @override
    def draw(self, context: Any) -> None:
        tree = _edited_tree(context)
        assert tree is not None  # poll
        layout: Any = self.layout  # never None while drawing
        if shows_tree(tree):
            property_display.draw_properties(layout, context, PROPERTY_VIEW_NAME)


class PROSCENIUM_PT_cook_viewer_property_metadata(_CookInspectorPanel, bpy.types.Panel):  # noqa: N801
    """A summary of the property the Viewer's property viewer selects."""

    bl_label = "Viewer Property Metadata"
    bl_options = {"DEFAULT_CLOSED"}  # noqa: RUF012 - Blender's panel field

    @override
    def draw(self, context: Any) -> None:
        tree = _edited_tree(context)
        assert tree is not None  # poll
        layout: Any = self.layout  # never None while drawing
        if shows_tree(tree):
            property_display.draw_metadata(layout, context, PROPERTY_VIEW_NAME)


# In the order they show, below the Cook panel.
CLASSES = (PROSCENIUM_PT_cook_viewer, PROSCENIUM_PT_cook_viewer_properties, PROSCENIUM_PT_cook_viewer_property_metadata)


def register() -> None:
    """Create the views; the widgets are registered."""
    display.create_view(VIEW_NAME, shows_in_region, tree_selection_changed)
    property_display.create_view(PROPERTY_VIEW_NAME, shows_in_region, on_jump_to_target=jump_to_target)


def unregister() -> None:
    """Remove the views."""
    property_display.remove_view(PROPERTY_VIEW_NAME)
    display.remove_view(VIEW_NAME)
    forget_shown()
