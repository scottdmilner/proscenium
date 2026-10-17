"""The compiled core and its bpy-free Python. Must not import bpy (enforced by tests/bpy_free).

The compiled module, _core, links Blender's usd_ms without embedding a path to it, so it loads only
into a process that already has that library.
"""

# Only for processes without bpy, such as tests/bpy_free: importing pxr loads Blender's usd_ms.
from pxr import Tf  # noqa: F401
