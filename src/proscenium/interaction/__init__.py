"""Interaction with a binding's display: its correspondence, read from Blender data (interaction-contract.md).

Tier 4, beside proscenium.synchronization: it may import proscenium.binding and the compiled core. It exports its
modules: the display elements and the core's correspondence over them (display_correspondence).
"""

from . import display_correspondence

__all__ = ["display_correspondence"]
