"""M5's stub application layer: a placeholder per partition, prepared apart (pipeline.md#blender-application).

Each of the plan's placeholders becomes an object drawing its bounding box and the bounds mesh it draws: the eight
corners of its local bounds, or no vertices when the plan has none. They're prepared in a staging collection no scene
links, so nothing prepared is visible, and preparation only creates datablocks: it never changes one the published
generation reaches (TXN-05). Each is held in the prepared work as soon as it exists (prepared_work).

The roles are a copy's, so each prepared resource takes the key of the published entry with its identity, or a new one
(manifests.entry_keys), and the entries preparation makes are the manifest a publication writes.

A cache call has it key the published placeholders' transforms at the time codes it caches, in an action per object
(key_time_codes), holding how to undo each change in the prepared work first, so a failing call removes the keys it
added and unassigns the actions it made. M7 replaces this layer; a sheared world transform, which needs a shear
parent, is M7's, as are cached bounds and content appearing at a cached time code.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

import bpy
from mathutils import Matrix

from ..binding.persistence import manifests

if TYPE_CHECKING:
    from collections.abc import Mapping

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


def key_time_codes(
    plans: Mapping[float, _core.Plan], published: manifests.Manifest, own: float, work: PreparedWork
) -> dict[str, manifests.EntryChange]:
    """Key each published placeholder's transform at each of plans' time codes; the manifest changes it makes.

    Each change to a published object is undoable through work.undo. A placeholder object first keyed gets an
    action, made and held in work, and is keyed at own, the generation's
    time code, as it shows it, too. Keys are constant, so a frame shows the latest key at or before it. The changes are
    each new action's entry, with its object's identity, and its object's, using it. A placeholder the published
    generation lacks, as one appearing only at a cached time code, is M7's. Raises whatever Blender raises.
    """
    keys = {identity: key for key, e in published.entries.items() if (identity := e.identity) is not None}
    changes: dict[str, manifests.EntryChange] = {}
    for time_code, plan in plans.items():
        for placeholder in plan.placeholders:
            resource = plan.resources[placeholder.object]
            object_identity = manifests.CopyResourceIdentity(
                manifests.RepresentationRole(resource.role), resource.entity, resource.place
            )
            if (object_key := keys.get(object_identity)) is None:
                continue
            obj = published.entries[object_key].datablock
            if obj is None:  # the user deleted it; the next synchronization replaces it
                continue
            assert isinstance(obj, bpy.types.Object)
            action_identity = object_identity._replace(role=manifests.RepresentationRole.ACTION)
            if action_identity not in keys:
                action_key = keys[action_identity] = manifests.new_entry_key()
                _new_action(obj, action_key, own, work)
                entry = published.entries[object_key]
                changes[action_key] = manifests.EntryChange(entry.covers, action_identity.role, [], entry.place)
                uses = [*entry.uses, action_key]
                changes[object_key] = manifests.EntryChange(entry.covers, entry.role, uses, entry.place)
            action = None if obj.animation_data is None else obj.animation_data.action
            assert action is not None  # made for it now, or when a time code was first cached
            _insert_keys(action, obj, time_code, _world(placeholder.world), work)
    return changes


def _new_action(obj: bpy.types.Object, action_key: str, own: float, work: PreparedWork) -> None:
    """Give obj an action, held in work under action_key, keyed at own with the transform obj shows."""
    action = bpy.data.actions.new(obj.name)
    work.track(action_key, manifests.RepresentationRole.ACTION, action)
    work.undo.append(obj.animation_data_clear)  # a placeholder has no animation data before its first action
    obj.animation_data_create().action = action
    _insert_keys(action, obj, own, obj.matrix_world, work)


def _insert_keys(
    action: bpy.types.Action, obj: bpy.types.Object, time_code: float, world: Matrix, work: PreparedWork
) -> None:
    """Key obj's transform in its action at time_code to world's, constant until its next key, undoably in work."""
    location, rotation, scale = world.decompose()
    # Slices, since the stubs don't make a Vector iterable; a placeholder keeps the default rotation mode.
    parts = {"location": location[:], "rotation_euler": rotation.to_euler("XYZ")[:], "scale": scale[:]}
    for data_path, values in parts.items():
        for index, value in enumerate(values):
            fcurve = action.fcurve_ensure_for_datablock(obj, data_path, index=index)
            work.undo.append(functools.partial(_remove_key, fcurve, time_code))  # before, so a failed insert is undone
            fcurve.keyframe_points.insert(time_code, value, options={"FAST"}).interpolation = "CONSTANT"


def _remove_key(fcurve: bpy.types.FCurve, time_code: float) -> None:
    """Remove fcurve's key at time_code, if it has one."""
    points = fcurve.keyframe_points
    if (point := next((p for p in points if p.co[0] == time_code), None)) is not None:
        points.remove(point)


def _corners(bounds: list[float]) -> list[tuple[float, float, float]]:
    """The eight corners of (min x, y, z, max x, y, z), or none for no bounds."""
    if not bounds:
        return []
    low, high = bounds[:3], bounds[3:]
    return [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]


def _world(matrix: Gf.Matrix4d) -> Matrix:
    """A plan's world matrix as Blender's: USD multiplies row vectors, Blender column vectors."""
    return Matrix([[matrix[row, col] for col in range(4)] for row in range(4)]).transposed()
