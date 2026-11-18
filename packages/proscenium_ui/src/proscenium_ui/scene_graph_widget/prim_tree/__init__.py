"""Prim trees: a stage's hierarchy as the rows a tree widget shows, its search, and what it says about each prim.

It reads the stage with Blender's bundled pxr and imports nothing of Blender's, so it tests in bpy_free. It exports
its modules: the tree and its rows (prim_rows), its search (prim_search), what it says about a prim
(prim_descriptions), and one tree as a widget shows it (tree_views); and the tree and the view, PrimTree and
PrimTreeView. The details it reads of a prim are `widget_model.prim_details`'.
"""

from . import prim_descriptions, prim_rows, prim_search, tree_views
from .prim_rows import PrimTree
from .tree_views import PrimTreeView

__all__ = ["PrimTree", "PrimTreeView", "prim_descriptions", "prim_rows", "prim_search", "tree_views"]
