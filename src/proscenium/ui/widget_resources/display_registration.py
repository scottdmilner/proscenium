"""Registering what the widgets share: the clipboard, guide line, and key operators, and the icons' previews.

Each widget registers it with its own registration, and several may be registered at once, so it's registered with
the first and unregistered with the last.
"""

from __future__ import annotations

import bpy

from . import badge_icons, clipboard_operators, keyframe_icons, list_keys, tinted_icons, tree_rows

# In registration order.
CLASSES = (*clipboard_operators.CLASSES, *tree_rows.CLASSES, *list_keys.CLASSES)


class _DisplayRegistrationState:
    registered_widget_count = 0


def register() -> None:
    """Register the shared classes and create the icons' collections, if no other widget has."""
    if _DisplayRegistrationState.registered_widget_count == 0:
        badge_icons.create_icons()
        keyframe_icons.create_icons()
        tinted_icons.create_icons()
        for cls in CLASSES:
            bpy.utils.register_class(cls)
    _DisplayRegistrationState.registered_widget_count += 1


def unregister() -> None:
    """Undo a widget's register, and once no widget is registered, unregister the shared classes and free the icons."""
    if _DisplayRegistrationState.registered_widget_count == 0:
        raise RuntimeError("no widget is registered")
    _DisplayRegistrationState.registered_widget_count -= 1
    if _DisplayRegistrationState.registered_widget_count == 0:
        for cls in reversed(CLASSES):
            bpy.utils.unregister_class(cls)
        tinted_icons.remove_icons()
        keyframe_icons.remove_icons()
        badge_icons.remove_icons()
