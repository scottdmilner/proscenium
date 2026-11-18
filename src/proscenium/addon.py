"""Blender registration. Imports bpy, so no bpy-free module imports this one."""

import proscenium_sync

from .interface import interface_registration

_registered = False


def register() -> None:
    """Register the synchronizer's record types and handlers, then the temporary UI."""
    global _registered
    proscenium_sync.register()
    interface_registration.register()
    _registered = True


def unregister() -> None:
    """Remove what register() added."""
    global _registered
    interface_registration.unregister()
    proscenium_sync.unregister()
    _registered = False


def is_registered() -> bool:
    """Whether register() has run without a matching unregister()."""
    return _registered
