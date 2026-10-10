"""Blender registration. Imports bpy; never import from proscenium.core code."""

import bpy

# Classes registered with Blender, in registration order.
CLASSES = ()

_registered = False


def register() -> None:
    global _registered
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _registered = True


def unregister() -> None:
    global _registered
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    _registered = False


def is_registered() -> bool:
    return _registered
