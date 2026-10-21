"""Save/reopen support, and a collection's content as plain data, for tests in the bpy wheel or the Blender binary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mathutils import Vector


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
