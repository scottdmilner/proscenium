"""What the widgets' models share: matching a search's text, and the composition arcs they mark.

It imports nothing of Blender's, so the widgets' models test in bpy_free. It exports its modules.
"""

from . import composition_arcs, text_matching

__all__ = ["composition_arcs", "text_matching"]
