"""Registering the scene graph's classes, window-manager properties, icons, key watchers, and load handler.

It places nothing in Blender's editors: a host registers its own panels, creates views, and draws them.
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from . import (
    badge_icons,
    widget_drawing,
    widget_hosting,
    widget_keys,
    widget_operators,
    widget_properties,
)

# In registration order: property groups before what refers to them.
CLASSES = (
    *widget_properties.CLASSES,
    *widget_operators.CLASSES,
    *widget_drawing.CLASSES,
    *widget_keys.CLASSES,
)


class _SceneGraphRegistrationState:
    is_registered = False


@persistent
def _file_loaded(*_args: object) -> None:
    # Loading a file replaces the window manager, whose properties aren't saved, and ends every modal operator.
    wm = bpy.context.window_manager
    if wm is not None:
        widget_properties.create_missing_view_properties(wm)
    widget_keys.forget_watchers()  # each window's watcher starts again when it next draws a view


def register() -> None:
    """Register the scene graph's classes and properties, create its icons, and start its key watchers."""
    if _SceneGraphRegistrationState.is_registered:
        raise RuntimeError("the scene graph is registered")
    badge_icons.create_icons()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    widget_properties.install_views_property()
    bpy.app.handlers.load_post.append(_file_loaded)
    widget_keys.start_watching()
    _SceneGraphRegistrationState.is_registered = True


def unregister() -> None:
    """Remove every view, stop the key watchers, and undo register."""
    widget_hosting.remove_all_views()
    widget_keys.stop_watching()  # each watcher ends at its next event
    bpy.app.handlers.load_post.remove(_file_loaded)
    widget_properties.remove_views_property()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    badge_icons.remove_icons()
    _SceneGraphRegistrationState.is_registered = False


def is_registered() -> bool:
    """Whether register() has run without a matching unregister()."""
    return _SceneGraphRegistrationState.is_registered
