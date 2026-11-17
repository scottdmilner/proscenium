"""Proscenium: one-way synchronization of composed OpenUSD stages into Blender.

This module must stay importable without bpy (tests/bpy_free). Blender-facing code is imported only on register,
through proscenium.addon.
"""


def register() -> None:
    """Register the extension's record types and handlers."""
    from . import addon

    addon.register()


def unregister() -> None:
    """Unregister what register() registered."""
    from . import addon

    addon.unregister()
