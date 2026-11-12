"""Local updates: kept copies changed in place at publication (change-matrix.md "Actions"), as the bridge's updates did.

A kept copy that moved has its world matrix set, or a sheared copy its shear parent's world matrix and its object's
basis below it; one whose participation changed has its hide flags set, all such copies' together, through a
collection no scene links, since assigning one runs Blender's update, which resyncs every collection
(application.prepare); and one whose bounds changed has its object pointed at a replacement bounds mesh. Each keeps its
identity and its Blender selection.

prepare_updates finds each kept copy's published objects and makes the replacement meshes beside the display, as
preparation makes partitions: each is held in the prepared work as it's made (TXN-08) and takes the key of the mesh it
replaces, so the new manifest names it there and the old one is retired, or released intact if unmanaged content uses
it (OWN-08). It changes nothing published. apply_updates, at publication, reads the matrices and participation it sets
from the plan's buffers, each value converted once where it's set and each view released before it returns (SNAP-13),
and changes the kept copies, adding how to undo each change to the publication's undo, so
a failure restores every kept object as it was: its data, its hide flags, and its transform, from its stored location,
rotation, and scale, which setting a matrix again needn't give back ([M4 plan](M04-prototypes.md), E2). A
replacement mesh takes the synchronization's next managed name (application.ManagedNames), which no other datablock
has, so it needs no renaming once the old one is gone (DECISIONS.md "Managed object names").
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import bpy

from ..binding.persistence import manifests
from . import application

if TYPE_CHECKING:
    from collections.abc import Buffer, Callable, Mapping, Sequence

    from ..core import _core
    from .partition_replacement import CopyUpdate
    from .preparation_resources import PreparationResources


@dataclass(frozen=True, slots=True)
class KeptCopyUpdate:
    """A kept copy publication changes: what changes, and the datablocks it changes; the values are the plan's."""

    copy_index: int  # in the plan
    change: CopyUpdate
    obj: bpy.types.Object  # the copy's object
    shear_parent: bpy.types.Object | None
    bounds_mesh: bpy.types.Mesh | None  # the replacement for a copy whose bounds changed


@dataclass(frozen=True, slots=True)
class Transform:
    """An object's own transform as Blender stores it, which restores exactly, as the bridge's does.

    Setting a matrix decomposes it again, which needn't give back the same components: a negative scale can return
    under another sign convention.
    """

    # Copies of Blender's values, typed Any: the bpy stubs type mathutils' Vector as a property descriptor.
    location: Any
    rotation_mode: str
    rotation: Any  # rotation_mode's own property: an Euler, a Quaternion, or the axis-angle values
    scale: Any

    @staticmethod
    def of(obj: bpy.types.Object) -> Transform:
        """Obj's transform, copied."""
        mode = obj.rotation_mode
        rotation = getattr(obj, _ROTATIONS.get(mode, "rotation_euler"))
        copied = rotation.copy() if hasattr(rotation, "copy") else tuple(rotation)
        return Transform(obj.location.copy(), mode, copied, obj.scale.copy())

    def restore(self, obj: bpy.types.Object) -> None:
        """Give obj this transform."""
        obj.rotation_mode = self.rotation_mode  # ty: ignore[invalid-assignment] - a mode read from an object
        obj.location = self.location
        setattr(obj, _ROTATIONS.get(self.rotation_mode, "rotation_euler"), self.rotation)
        obj.scale = self.scale


_ROTATIONS = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}  # else Euler


def prepare_updates(
    plan: _core.Plan,
    updated: Mapping[int, CopyUpdate],
    published: manifests.Manifest,
    work: PreparationResources,
    names: application.ManagedNames,
) -> list[KeptCopyUpdate]:
    """Each of updated's kept copies, by its index in plan, with its published objects; their replacement meshes made.

    Each replacement mesh is held in work under the published mesh's key, with that entry naming it, and named from
    names, the synchronization's. Raises application.ResourceOperationError, naming the mesh, when making one fails;
    what was made before stays in work.
    """
    copies = sorted(updated)
    if not copies:
        return []
    keys = {identity: key for key, e in published.entries.items() if (identity := e.identity) is not None}
    updates: list[KeptCopyUpdate] = []
    with contextlib.ExitStack() as views:  # each view released on return or raise (SNAP-13)

        def view(buffer: Buffer) -> memoryview:
            return views.enter_context(memoryview(buffer))

        objects, meshes, parents = (
            view(plan.copy_object_resource_indices),
            view(plan.copy_bounds_mesh_resource_indices),
            view(plan.copy_shear_parent_resource_indices),
        )
        resource_indices = [r for c in copies for r in (objects[c], meshes[c], parents[c]) if r >= 0]
        resources = dict(zip(resource_indices, plan.resources_at(resource_indices), strict=True))

        def published_key(resource_index: int) -> str:
            r = resources[resource_index]
            identity = manifests.CopyResourceIdentity(
                manifests.RepresentationRole(r.role), r.source_entity_path, r.object_index_in_copy
            )
            return keys[identity]

        bounds = application.local_bounds(plan, [c for c in copies if updated[c].bounds_changed], view)
        for copy in copies:
            change = updated[copy]
            obj = published.entries[published_key(objects[copy])].datablock
            parent = None if parents[copy] < 0 else published.entries[published_key(parents[copy])].datablock
            assert isinstance(obj, bpy.types.Object) and (parent is None or isinstance(parent, bpy.types.Object))
            mesh = None
            if change.bounds_changed:
                name = names.next_name(resources[objects[copy]].source_entity_path.rsplit("/", 1)[-1])
                mesh = _replacement_mesh(name, published_key(meshes[copy]), bounds[copy], published, work)
            updates.append(KeptCopyUpdate(copy, change, obj, parent, mesh))
    return updates


def _replacement_mesh(
    name: str,
    mesh_key: str,
    bounds: Sequence[float],
    published: manifests.Manifest,
    work: PreparationResources,
) -> bpy.types.Mesh:
    """A bounds mesh of bounds named name, held in work under mesh_key, whose entry names it."""
    try:
        mesh = bpy.data.meshes.new(name)
        work.track(mesh_key, manifests.RepresentationRole.BOUNDS_MESH, mesh)
        mesh.from_pydata(application.corners(bounds), [], [])
    except Exception as error:
        entity = published.entries[mesh_key].source_entity_paths[0]
        raise application.ResourceOperationError(manifests.RepresentationRole.BOUNDS_MESH, entity, error) from error
    work.manifest_entries[mesh_key] = dataclasses.replace(published.entries[mesh_key], datablock=mesh)
    return mesh


def apply_updates(plan: _core.Plan, updates: Sequence[KeptCopyUpdate], undo: list[Callable[[], object]]) -> None:
    """Set plan's values on each update's kept copy, adding how to undo each change to undo first.

    Raises what Blender raises.
    """
    if not updates:
        return
    with contextlib.ExitStack() as views:  # each view released on return or raise (SNAP-13)

        def view(buffer: Buffer) -> memoryview:
            return views.enter_context(memoryview(buffer))

        worlds, shears = view(plan.copy_world_matrices), view(plan.copy_shear_split_indices)
        parent_worlds, bases = view(plan.shear_parent_world_matrices), view(plan.shear_object_basis_matrices)
        for update in updates:
            obj, copy = update.obj, update.copy_index
            if update.bounds_mesh is not None:
                undo.append(functools.partial(setattr, obj, "data", obj.data))
                obj.data = update.bounds_mesh
            if not update.change.moved:
                continue
            if (shear := shears[copy]) < 0:
                undo.append(functools.partial(Transform.of(obj).restore, obj))
                obj.matrix_world = application.matrix_from_buffer(worlds, copy)
            else:
                parent = update.shear_parent
                assert parent is not None  # a sheared copy's
                undo.append(functools.partial(Transform.of(parent).restore, parent))
                undo.append(functools.partial(Transform.of(obj).restore, obj))
                parent.matrix_world = application.matrix_from_buffer(parent_worlds, shear)
                obj.matrix_basis = application.matrix_from_buffer(bases, shear)
        hiding = [update for update in updates if update.change.participation_changed]
        if hiding:
            visible = view(plan.copy_visible_in_viewport), view(plan.copy_visible_in_render)
            _set_hide_flags(hiding, visible, undo)


def _set_hide_flags(
    updates: Sequence[KeptCopyUpdate], visible: tuple[memoryview, memoryview], undo: list[Callable[[], object]]
) -> None:
    """Set the updates' hide flags together, through a collection no scene links, removed again after.

    visible is the plan's participation, viewport's and render's, by copy index.
    """
    undo.extend(
        functools.partial(_restore_hide_flags, update.obj, update.obj.hide_viewport, update.obj.hide_render)
        for update in updates
    )
    together = bpy.data.collections.new("Proscenium hide flags")
    try:
        for update in updates:
            together.objects.link(update.obj)
        for flag, shown in zip(("hide_viewport", "hide_render"), visible, strict=True):
            together.objects.foreach_set(flag, [not shown[update.copy_index] for update in updates])
    finally:
        bpy.data.batch_remove([together])


def _restore_hide_flags(obj: bpy.types.Object, hide_viewport: bool, hide_render: bool) -> None:
    obj.hide_viewport, obj.hide_render = hide_viewport, hide_render
