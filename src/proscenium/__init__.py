"""Proscenium: one-way synchronization of composed OpenUSD stages into Blender.

This module must stay importable without bpy so proscenium.core, the compiled
core and its bpy-free Python, can be tested outside Blender. Blender-facing code
is imported only on register, through proscenium.addon.
"""


def register() -> None:
    """Register the extension: its record types and its handlers (proscenium.addon)."""
    from . import addon

    addon.register()


def unregister() -> None:
    """Unregister what register() registered."""
    from . import addon

    addon.unregister()
