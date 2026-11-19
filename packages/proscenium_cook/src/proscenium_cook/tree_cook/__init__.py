"""The cook's compiled module, _cook, which links Blender's usd_ms without embedding a path to it.

It loads only into a process that already has that library. Its names are the package's own.
"""

# Importing pxr.Usd loads Blender's usd_ms, which only processes without bpy (such as tests/bpy_free) lack, and
# registers the Python converters for USD types that _cook's arguments will use.
from pxr import Usd  # noqa: F401

from ._cook import NodeDefinitions, TreeCook, diagnostic_codes, prim_name_from_node_id, usd_version

__all__ = ["NodeDefinitions", "TreeCook", "diagnostic_codes", "prim_name_from_node_id", "usd_version"]
