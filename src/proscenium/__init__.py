"""Proscenium: one-way synchronization of composed OpenUSD stages into Blender.

Blender calls register and unregister when it enables and disables the extension.
"""

from .addon import register, unregister

__all__ = ["register", "unregister"]
