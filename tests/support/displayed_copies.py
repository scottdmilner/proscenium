"""What a binding's display shows of each drawn copy, read from Blender, for support/bounds_check.py.

A copy is its object's manifest entry: its source entity, its hide flags, and its mesh's vertices in world space. A
world matrix is composed from each object's basis and its parents', as Blender composes them, rather than read from
matrix_world, which Blender updates only with the depsgraph. Evaluated, a mesh's vertices are its modifiers' output,
as the depsgraph last evaluated it, such as a frames modifier's sample.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from proscenium_sync.binding_persistence import id_property_records
from proscenium_sync.binding_persistence.manifests import RepresentationRole
from proscenium_sync.binding_runtime import ownership

from .bounds_check import DisplayedCopy

if TYPE_CHECKING:
    from mathutils import Matrix

    from proscenium_sync.source_access import BindingId


def _objects(binding_id: BindingId) -> list[tuple[str, bpy.types.Object]]:
    """Each drawn copy's object, with its source entity, from the binding's manifest."""
    manifest = ownership.manifest(binding_id)
    assert isinstance(manifest, id_property_records.LoadedRecord), manifest
    found = []
    for entry in manifest.record.entries.values():
        if entry.role is RepresentationRole.OBJECT:
            assert isinstance(entry.datablock, bpy.types.Object), entry
            found.append((entry.source_entity_paths[0], entry.datablock))
    return found


def _world(obj: bpy.types.Object) -> Matrix:
    basis = obj.matrix_basis
    return basis if obj.parent is None else _world(obj.parent) @ obj.matrix_parent_inverse @ basis


def displayed_copies(binding_id: BindingId, *, evaluated: bool = False) -> list[DisplayedCopy]:
    """What the binding's published display shows of each drawn copy, its meshes evaluated if asked."""
    depsgraph = bpy.context.evaluated_depsgraph_get() if evaluated else None
    found = []
    for source, obj in _objects(binding_id):
        world = _world(obj)
        mesh = obj.data if depsgraph is None else obj.evaluated_get(depsgraph).data
        vertices = tuple(tuple((world @ v.co)[:]) for v in mesh.vertices) if isinstance(mesh, bpy.types.Mesh) else ()
        found.append(DisplayedCopy(source, not obj.hide_viewport, not obj.hide_render, vertices))  # ty: ignore[invalid-argument-type]
    return found


def unique_mesh_data_count(binding_id: BindingId) -> int:
    """How many distinct meshes the binding's display draws, the aggregate the end-to-end checks record (ASTD-03)."""
    return len({obj.data for _, obj in _objects(binding_id) if isinstance(obj.data, bpy.types.Mesh)})
