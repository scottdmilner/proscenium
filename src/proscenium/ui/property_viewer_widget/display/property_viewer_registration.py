"""Registering the property viewer's classes, window-manager properties, key watching, and load handler.

It places nothing in Blender's editors: a host registers its own panels, creates views, and draws them.
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from ...widget_resources import display_registration
from . import (
    property_viewer_drawing,
    property_viewer_hosting,
    property_viewer_keys,
    property_viewer_operators,
    property_viewer_properties,
    property_viewer_views,
)

# In registration order: property groups before what refers to them.
CLASSES = (
    *property_viewer_properties.CLASSES,
    *property_viewer_operators.CLASSES,
    *property_viewer_drawing.CLASSES,
)


class _PropertyViewerRegistrationState:
    is_registered = False


@persistent
def _file_loaded(*_args: object) -> None:
    # Loading a file replaces the window manager, whose properties aren't saved, and ends every modal operator; each
    # window's key watcher starts again when it next draws a view. It ends any text edit too.
    wm = bpy.context.window_manager
    if wm is not None:
        property_viewer_properties.create_missing_view_properties(wm)
    property_viewer_views.stop_entering_search_text()


def register() -> None:
    """Register what the widgets share, the property viewer's classes and properties, and watch its keys."""
    if _PropertyViewerRegistrationState.is_registered:
        raise RuntimeError("the property viewer is registered")
    display_registration.register()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    property_viewer_properties.install_views_property()
    bpy.app.handlers.load_post.append(_file_loaded)
    property_viewer_keys.start_watching()
    _PropertyViewerRegistrationState.is_registered = True


def unregister() -> None:
    """Remove every view, stop watching its keys, and undo register."""
    property_viewer_hosting.remove_all_views()
    property_viewer_keys.stop_watching()  # each watcher ends at its next event, if no other widget's lists are left
    bpy.app.handlers.load_post.remove(_file_loaded)
    property_viewer_properties.remove_views_property()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    display_registration.unregister()
    _PropertyViewerRegistrationState.is_registered = False


def is_registered() -> bool:
    """Whether register() has run without a matching unregister()."""
    return _PropertyViewerRegistrationState.is_registered
