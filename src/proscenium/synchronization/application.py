"""M5's stub application layer: a placeholder per partition, prepared apart (pipeline.md#blender-application).

Each of the plan's placeholders becomes an object drawing its bounding box and the bounds mesh it draws: the eight
corners of its local bounds, or no vertices when the plan has none. They're prepared in a staging collection no scene
links, so nothing prepared is visible, and preparation only creates datablocks: it never changes one the published
generation reaches (TXN-05).

The roles are a copy's, so each prepared resource takes the key of the published entry with its identity, or a new one
(persistence.entry_keys), and the entries preparation makes are the manifest a publication writes. M7 replaces this
layer; a sheared world transform, which needs a shear parent, is M7's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import bpy
from mathutils import Matrix

from ..binding.persistence import CopyResourceIdentity, ManifestEntry, RepresentationRole, entry_keys

if TYPE_CHECKING:
    from pxr import Gf

    from ..binding.persistence import Manifest
    from ..core._core import Plan


@dataclass
class PreparedWork:
    """The prepared work a preparation has made so far, so a failure partway leaves it all to dispose of."""

    staging: bpy.types.Collection  # holds the prepared objects; no scene links it
    datablocks: dict[str, bpy.types.ID] = field(default_factory=dict)  # entry key -> datablock, in creation order
    entries: dict[str, ManifestEntry] = field(default_factory=dict)  # entry key -> its entry, once complete


def new_prepared_work() -> PreparedWork:
    """Empty prepared work, with its staging collection."""
    return PreparedWork(bpy.data.collections.new("Proscenium prepared"))


def prepare(plan: Plan, published: Manifest, prepared: PreparedWork) -> None:
    """Make plan's placeholders in prepared's staging collection, adding each datablock to prepared as it's made.

    published is the binding's published manifest, whose entries' keys the prepared resources with their identities
    take. Raises whatever Blender raises; what was made before stays in prepared.
    """
    identities = [CopyResourceIdentity(RepresentationRole(r.role), r.entity, r.place) for r in plan.resources]
    keys = entry_keys(published, identities)
    for placeholder in plan.placeholders:
        mesh_key, object_key = keys[placeholder.bounds_mesh], keys[placeholder.object]
        source = plan.resources[placeholder.object].entity
        name = source.rsplit("/", 1)[-1]
        mesh = bpy.data.meshes.new(name)
        prepared.datablocks[mesh_key] = mesh
        mesh.from_pydata(_corners(list(placeholder.bounds)), [], [])
        obj = bpy.data.objects.new(name, mesh)
        prepared.datablocks[object_key] = obj
        prepared.staging.objects.link(obj)
        obj.display_type = "BOUNDS"
        obj.matrix_world = _world(placeholder.world)
        for index, key, datablock in (
            (placeholder.bounds_mesh, mesh_key, mesh),
            (placeholder.object, object_key, obj),
        ):
            resource = plan.resources[index]
            uses = [keys[used] for used in resource.uses]
            prepared.entries[key] = ManifestEntry(
                datablock, list(resource.covers), identities[index].role, uses, resource.place
            )


def dispose(prepared: PreparedWork) -> None:
    """Remove what prepared holds, its staging collection included."""
    bpy.data.batch_remove([*prepared.datablocks.values(), prepared.staging])
    prepared.datablocks.clear()
    prepared.entries.clear()


def _corners(bounds: list[float]) -> list[tuple[float, float, float]]:
    """The eight corners of (min x, y, z, max x, y, z), or none for no bounds."""
    if not bounds:
        return []
    low, high = bounds[:3], bounds[3:]
    return [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]


def _world(matrix: Gf.Matrix4d) -> Matrix:
    """A plan's world matrix as Blender's: USD multiplies row vectors, Blender column vectors."""
    return Matrix([[matrix[row, col] for col in range(4)] for row in range(4)]).transposed()
