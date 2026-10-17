"""The compiled core and its bpy-free Python. Must not import bpy (enforced by tests/bpy_free).

The compiled module, _core, links Blender's usd_ms without embedding a path to it, so it loads only
into a process that already has that library.
"""

# Importing pxr.Usd loads Blender's usd_ms, which only processes without bpy (such as tests/bpy_free) lack, and
# registers the Python converters for USD types that _core's arguments use, which any process may lack.
from pxr import Usd  # noqa: F401
