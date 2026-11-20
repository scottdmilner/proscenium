"""Registration of the temporary UI: its scene properties, classes, tool, subscriptions, and the cook's node tree.

proscenium.addon registers it after the synchronizer. It registers proscenium_ui's widgets once, and each inspector,
the source inspector and the cook inspector, adds and removes its own views, independently of the other. After a file
loads, the message-bus subscriptions, which a load clears, are made again, and after a load, an undo, or a redo,
selectability is recomputed from the active tool rather than kept as the file or the undo step stored it. After an undo
or a redo, the source inspector's tree takes up the restored source selection.
"""

from __future__ import annotations

from typing import Any

import bpy
from bpy.app.handlers import persistent

from proscenium_ui.property_viewer_widget import display as property_display
from proscenium_ui.scene_graph_widget import display as scene_graph_display

from . import binding_panel, cook_inspector, cook_node_types, cook_panel, source_inspector, source_select_tool

CLASSES = (
    *binding_panel.CLASSES,
    *source_select_tool.CLASSES,
    *source_inspector.CLASSES,
    *cook_panel.CLASSES,
    *cook_inspector.CLASSES,  # below the Cook panel
)


@persistent
def _file_loaded(*_args: object) -> None:
    cook_panel.forget_cooks()  # the loaded file's trees are others, though a session UID may repeat
    cook_node_types.schedule_all_link_marking()  # a loaded tree's links load valid
    source_select_tool.subscribe_to_tools()
    source_select_tool.update_selectability()


@persistent
def _undone_or_redone(*_args: object) -> None:
    source_select_tool.update_selectability()  # an undo step may hold selectability from before the tool's activation
    cook_node_types.schedule_all_link_marking()  # an undo step's trees load with their links valid
    if bpy.context.scene is not None:
        source_inspector.source_selection_changed(bpy.context.scene)  # undo restores the selection, not the tree


def register() -> None:
    """Register the UI's scene properties, classes, and tool, and follow the active tool."""
    scene_type: Any = bpy.types.Scene
    # A fixed list, read once: an enum's items must stay referenced from Python, or Blender may show garbage.
    setattr(scene_type, source_select_tool.LEVEL_PROPERTY, bpy.props.EnumProperty(items=source_select_tool.levels()))
    cook_node_types.register()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.utils.register_tool(source_select_tool.PROSCENIUM_TT_source_select, separator=True)
    # The widgets, once for both inspectors, which each add their own views.
    scene_graph_display.register()
    property_display.register()
    source_inspector.register()
    cook_inspector.register()
    bpy.app.handlers.load_post.append(_file_loaded)
    bpy.app.handlers.undo_post.append(_undone_or_redone)
    bpy.app.handlers.redo_post.append(_undone_or_redone)
    source_select_tool.subscribe_to_tools()
    source_select_tool.update_selectability()


def unregister() -> None:
    """Remove what register() added."""
    source_select_tool.unsubscribe_from_tools()
    bpy.app.handlers.load_post.remove(_file_loaded)
    bpy.app.handlers.undo_post.remove(_undone_or_redone)
    bpy.app.handlers.redo_post.remove(_undone_or_redone)
    source_inspector.unregister()
    cook_inspector.unregister()
    property_display.unregister()  # would remove any view left
    scene_graph_display.unregister()
    bpy.utils.unregister_tool(source_select_tool.PROSCENIUM_TT_source_select)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    cook_node_types.unregister()
    cook_panel.forget_cooks()
    delattr(bpy.types.Scene, source_select_tool.LEVEL_PROPERTY)
