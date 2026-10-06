"""Proscenium: one-way synchronization of composed OpenUSD stages into Blender.

This module must stay importable without bpy so pure-Python subpackages
(proscenium.core) can be unit tested outside Blender. Blender-facing code lives
in proscenium.addon and is imported only on register.
"""


def register() -> None:
    from . import addon

    addon.register()


def unregister() -> None:
    from . import addon

    addon.unregister()
