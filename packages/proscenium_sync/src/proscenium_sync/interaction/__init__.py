"""Interaction with a binding's display: its correspondence, read from Blender data (interaction-contract.md).

It exports its modules: the display elements and the planner's correspondence over them (display_correspondence), and
Blender's selection of the elements, mirrored and read (blender_selection).
"""

from . import blender_selection, display_correspondence

__all__ = ["blender_selection", "display_correspondence"]
