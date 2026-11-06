"""M5's stub application layer: a placeholder per partition, prepared apart (pipeline.md#blender-application).

Each of the plan's placeholders becomes an object drawing its bounding box and the bounds mesh it draws: the eight
corners of its local bounds, or no vertices when the plan has none. They're prepared in a staging collection no scene
links, so nothing prepared is visible, and preparation only creates datablocks: it never changes one the published
generation reaches (TXN-05). Each is held in the prepared work as soon as it exists (prepared_work).

The roles are a copy's, so each prepared resource takes the key of the published entry with its identity, or a new one
(manifests.entry_keys), and the entries preparation makes are the manifest a publication writes. M7 replaces this
layer; a sheared world transform, which needs a shear parent, is M7's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
from mathutils import Matrix

from ..binding.persistence import manifests

if TYPE_CHECKING:
    from pxr import Gf

    from ..core import _core
    from .prepared_work import PreparedWork

REPRESENTATION_VERSION = 1  # the representation this layer applies, which the planning context names


def prepare(plan: _core.Plan, published: manifests.Manifest, work: PreparedWork) -> None:
    """Make plan's placeholders in work's staging collection, holding each datablock as it's made (TXN-08).

    published is the binding's published manifest, whose entries' keys the prepared resources with their identities
    take. Raises whatever Blender raises; what was made before stays in work, held.
    """
    identities = [
        manifests.CopyResourceIdentity(manifests.RepresentationRole(r.role), r.entity, r.place) for r in plan.resources
    ]
    keys = manifests.entry_keys(published, identities)
    for placeholder in plan.placeholders:
        mesh_key, object_key = keys[placeholder.bounds_mesh], keys[placeholder.object]
        source = plan.resources[placeholder.object].entity
        name = source.rsplit("/", 1)[-1]
        mesh = bpy.data.meshes.new(name)
        work.track(mesh_key, identities[placeholder.bounds_mesh].role, mesh)
        mesh.from_pydata(_corners(list(placeholder.bounds)), [], [])
        obj = bpy.data.objects.new(name, mesh)
        work.track(object_key, identities[placeholder.object].role, obj)
        work.staging.objects.link(obj)
        obj.display_type = "BOUNDS"
        obj.matrix_world = _world(placeholder.world)
        for index, key, datablock in (
            (placeholder.bounds_mesh, mesh_key, mesh),
            (placeholder.object, object_key, obj),
        ):
            resource = plan.resources[index]
            uses = [keys[used] for used in resource.uses]
            work.entries[key] = manifests.ManifestEntry(
                datablock, list(resource.covers), identities[index].role, uses, resource.place
            )


def _corners(bounds: list[float]) -> list[tuple[float, float, float]]:
    """The eight corners of (min x, y, z, max x, y, z), or none for no bounds."""
    if not bounds:
        return []
    low, high = bounds[:3], bounds[3:]
    return [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]


def _world(matrix: Gf.Matrix4d) -> Matrix:
    """A plan's world matrix as Blender's: USD multiplies row vectors, Blender column vectors."""
    return Matrix([[matrix[row, col] for col in range(4)] for row in range(4)]).transposed()
