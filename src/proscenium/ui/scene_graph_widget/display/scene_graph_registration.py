"""Registering the scene graph's classes, window-manager properties, key watchers, and load handler.

It places nothing in Blender's editors: a host registers its own panels, creates views, and draws them.
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from ...widget_resources import display_registration
from . import (
    scene_graph_drawing,
    scene_graph_hosting,
    scene_graph_keys,
    scene_graph_operators,
    scene_graph_properties,
    scene_graph_views,
)

# In registration order: property groups before what refers to them.
CLASSES = (
    *scene_graph_properties.CLASSES,
    *scene_graph_operators.CLASSES,
    *scene_graph_drawing.CLASSES,
    *scene_graph_keys.CLASSES,
)


class _SceneGraphRegistrationState:
    is_registered = False


@persistent
def _file_loaded(*_args: object) -> None:
    # Loading a file replaces the window manager, whose properties aren't saved, and ends every modal operator; each
    # window's key watcher starts again when it next draws a view. It ends any text edit too.
    wm = bpy.context.window_manager
    if wm is not None:
        scene_graph_properties.create_missing_view_properties(wm)
    scene_graph_views.stop_entering_search_text()


def register() -> None:
    """Register what the widgets share, the scene graph's classes and properties, and start its key watchers."""
    if _SceneGraphRegistrationState.is_registered:
        raise RuntimeError("the scene graph is registered")
    display_registration.register()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    scene_graph_properties.install_views_property()
    bpy.app.handlers.load_post.append(_file_loaded)
    scene_graph_keys.start_watching()
    _SceneGraphRegistrationState.is_registered = True


def unregister() -> None:
    """Remove every view, stop the key watchers, and undo register."""
    scene_graph_hosting.remove_all_views()
    scene_graph_keys.stop_watching()  # each watcher ends at its next event
    bpy.app.handlers.load_post.remove(_file_loaded)
    scene_graph_properties.remove_views_property()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    display_registration.unregister()
    _SceneGraphRegistrationState.is_registered = False


def is_registered() -> bool:
    """Whether register() has run without a matching unregister()."""
    return _SceneGraphRegistrationState.is_registered
