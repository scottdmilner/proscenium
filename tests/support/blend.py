"""Save/reopen, collection content, and managed names, for tests in the bpy wheel or the Blender binary.

A collection's content comes back as plain data, and a managed datablock's name gives back the prim it is named for.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import bpy

# A managed object's name before its prim's (DECISIONS.md "Managed object names"), as application.py writes it.
_MANAGED_PREFIX = re.compile(r"~\d{6}\.\d{7} ")

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mathutils import Vector


def prim_name(datablock: bpy.types.ID) -> str:
    """The name of the prim a managed datablock is named for.

    An object's or bounds mesh's name after its generation and ordinal, or another datablock's name without Blender's
    numeric suffix (`Still.001`).
    """
    name = _MANAGED_PREFIX.sub("", datablock.name, count=1)
    return name if name != datablock.name else name.split(".")[0]


def save_and_reopen(path: Path) -> None:
    """Save the open file to `path` (normally under the test's tmp_path) and open it again.

    Every bpy reference held before the call is invalid afterwards; look
    datablocks up again by name. Handlers that are not @persistent are removed
    by the reopen, as with any file load.

    open_mainfile rebuilds all data from the file, even for the same path; only
    process-level state (Python, persistent handlers, add-ons, USD) carries over.
    """
    bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=str(path))


def _rounded(values: Vector | Sequence[float]) -> list[float]:
    return [round(v, 6) for v in values[:]]  # a slice: the stubs don't make a Vector iterable


def collection_content(collection: bpy.types.Collection) -> dict[str, dict[str, Any]]:
    """The collection's objects as plain, JSON-compatible data, by object name, read with bpy alone.

    Each object's world matrix and parent and, for a mesh, its vertices, faces, and materials
    (name and viewport color): what a saved display shows, comparable across a reopen or a process.
    """
    content = {}
    for obj in collection.objects:
        mesh = obj.data if isinstance(obj.data, bpy.types.Mesh) else None
        content[obj.name] = {
            "matrix": [_rounded(row) for row in obj.matrix_world],
            "parent": obj.parent and obj.parent.name,
            "vertices": mesh and [_rounded(v.co) for v in mesh.vertices],
            "faces": mesh and [list(p.vertices) for p in mesh.polygons],
            "materials": mesh and [[m.name, _rounded(m.diffuse_color)] for m in mesh.materials if m],
        }
    return content
