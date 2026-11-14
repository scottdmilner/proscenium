"""Prim trees: a stage's hierarchy as the rows a tree widget shows, its search, and what it says about each prim.

It reads the stage with Blender's bundled pxr and imports nothing of Blender's, so it tests in bpy_free. It exports
two of its modules, and the tree, row, and view types the display uses; the details it reads of a prim are
`widget_model.prim_details`'.
"""

from . import prim_descriptions, prim_search
from .prim_tree import PrimTree, TreeRow
from .prim_tree_view import PrimTreeView

__all__ = [
    "PrimTree",
    "PrimTreeView",
    "TreeRow",
    "prim_descriptions",
    "prim_search",
]
