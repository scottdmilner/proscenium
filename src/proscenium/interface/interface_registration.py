"""Registration of the temporary UI: its scene properties, classes, tool, and subscriptions (M7 plan, F1).

proscenium.addon registers it after the records. After a file loads, the message-bus subscriptions, which a load
clears, are made again, and after a load, an undo, or a redo, selectability is recomputed from the active tool rather
than kept as the file or the undo step stored it.
"""

from __future__ import annotations

from typing import Any

import bpy
from bpy.app.handlers import persistent

from . import binding_panel, source_select_tool

CLASSES = (*binding_panel.CLASSES, *source_select_tool.CLASSES)


@persistent
def _file_loaded(*_args: object) -> None:
    source_select_tool.subscribe_to_tools()
    source_select_tool.update_selectability()


@persistent
def _undone_or_redone(*_args: object) -> None:
    source_select_tool.update_selectability()  # an undo step may hold selectability from before the tool's activation


def register() -> None:
    """Register the UI's scene properties, classes, and tool, and follow the active tool."""
    scene_type: Any = bpy.types.Scene
    # A fixed list, read once: an enum's items must stay referenced from Python, or Blender may show garbage.
    setattr(scene_type, source_select_tool.LEVEL_PROPERTY, bpy.props.EnumProperty(items=source_select_tool.levels()))
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.utils.register_tool(source_select_tool.PROSCENIUM_TT_source_select, separator=True)
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
    bpy.utils.unregister_tool(source_select_tool.PROSCENIUM_TT_source_select)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    delattr(bpy.types.Scene, source_select_tool.LEVEL_PROPERTY)
