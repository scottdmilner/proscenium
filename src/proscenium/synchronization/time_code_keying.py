"""Keying the published display at a cache call's time codes (pipeline.md#cached-time-codes; M7 plan, D1, D2).

key_time_codes keys each published copy that varies at every time code the call caches: its object's transform and
hide flags, and, when the plan splits its world transform at a time code, its shear parent's world transform and its
object's basis below it. A copy's object and its shear parent share one action, each through a slot of its own, so a
copy's action has one identity, its object's with the action's role. Keys are constant, so a frame shows the latest
key at or before it.

A copy keyed for the first time gets its action, made and held in the prepared work, keyed at the generation's own
time code and at the time codes cached before with what its object and shear parent show, which they showed there,
since they weren't keyed. A copy sheared at a cached time code but not at the generation's own gets a shear parent,
made, held, and linked into the destination, identity at the time codes it isn't sheared at; a copy sheared at its
own but not at a cached time code keeps its parent, identity there. Each change to a published resource has its undo
in the prepared work before it's made, so a failing call removes the keys it added, unparents and unlinks what it
parented, and its prepared work is disposed of (CACHE-03).
"""

from __future__ import annotations

import contextlib
import functools
from typing import TYPE_CHECKING

import bpy
from mathutils import Matrix

from ..binding.persistence import manifests
from . import application

if TYPE_CHECKING:
    from collections.abc import Buffer, Collection, Iterable, Mapping, Sequence

    from ..core import _core
    from .preparation_resources import PreparationResources

_NO_SHEAR = -1  # in the plan's copy_shear_split_indices: the copy's world transform isn't split
_HIDE_FLAGS = ("hide_viewport", "hide_render")


def key_time_codes(  # noqa: PLR0913 - the plans, what they key, and the generation they key
    plans: Mapping[float, _core.Plan],
    varying_sources: Collection[str] | None,
    published: manifests.Manifest,
    destination: bpy.types.Collection,
    own: float,
    cached_before: Sequence[float],
    work: PreparationResources,
) -> dict[str, manifests.ManifestEntryChange]:
    """Key each published copy of varying_sources at each of plans' time codes; the manifest changes it makes.

    varying_sources names copies by source entity, or is None for every copy. destination holds published, the
    generation's manifest, published at own and cached at cached_before. The changes are each new action's and shear
    parent's entry, and the entries of the objects and parents that use them. A copy the published generation lacks,
    as one appearing only at a cached time code, is Phase D's. Raises whatever Blender raises.
    """
    keys = {identity: key for key, e in published.entries.items() if (identity := e.identity) is not None}
    changes: dict[str, manifests.ManifestEntryChange] = {}
    names = application.ManagedNames()
    shown_before = (own, *cached_before)
    for time_code, plan in plans.items():
        with contextlib.ExitStack() as views:  # each view released on return or raise (SNAP-13)

            def view(buffer: Buffer) -> memoryview:
                return views.enter_context(memoryview(buffer))

            objects, parents = view(plan.copy_object_resource_indices), view(plan.copy_shear_parent_resource_indices)
            shears, worlds = view(plan.copy_shear_split_indices), view(plan.copy_world_matrices)
            parent_worlds, bases = view(plan.shear_parent_world_matrices), view(plan.shear_object_basis_matrices)
            viewport, render = view(plan.copy_visible_in_viewport), view(plan.copy_visible_in_render)
            object_resources = plan.resources_at(objects.tolist())
            for copy, resource in enumerate(object_resources):
                source = resource.source_entity_path
                if varying_sources is not None and source not in varying_sources:
                    continue
                identity = manifests.CopyResourceIdentity(
                    manifests.RepresentationRole(resource.role), source, resource.object_index_in_copy
                )
                if (object_key := keys.get(identity)) is None:
                    continue  # one the generation lacks
                obj = published.entries[object_key].datablock
                if obj is None:  # the user deleted it; the next synchronization replaces it
                    continue
                assert isinstance(obj, bpy.types.Object)
                action = _ensure_action(obj, identity, object_key, keys, published, shown_before, changes, work)
                shear = shears[copy]
                parent = obj.parent
                if shear != _NO_SHEAR and parent is None:
                    [parent_resource] = plan.resources_at([parents[copy]])
                    parent_identity = manifests.CopyResourceIdentity(
                        manifests.RepresentationRole.SHEAR_PARENT, source, parent_resource.object_index_in_copy
                    )
                    action_key = keys[identity._replace(role=manifests.RepresentationRole.ACTION)]
                    parent = _new_shear_parent(
                        obj,
                        parent_identity,
                        (object_key, action_key),
                        keys,
                        published,
                        destination,
                        names,
                        changes,
                        work,
                    )
                    _key_transform(action, parent, shown_before, Matrix.Identity(4), work)
                if shear != _NO_SHEAR:
                    assert parent is not None
                    parent_world = application.matrix_from_buffer(parent_worlds, shear)
                    basis = application.matrix_from_buffer(bases, shear)
                else:
                    parent_world, basis = Matrix.Identity(4), application.matrix_from_buffer(worlds, copy)
                _key_transform(action, obj, (time_code,), basis, work)
                if parent is not None:
                    _key_transform(action, parent, (time_code,), parent_world, work)
                _key_hide_flags(action, obj, (time_code,), (not viewport[copy], not render[copy]), work)
    return changes


def _ensure_action(  # noqa: PLR0913 - the object, its entry, and the call's state
    obj: bpy.types.Object,
    object_identity: manifests.CopyResourceIdentity,
    object_key: str,
    keys: dict[manifests.CopyResourceIdentity, str],
    published: manifests.Manifest,
    shown_before: Sequence[float],
    changes: dict[str, manifests.ManifestEntryChange],
    work: PreparationResources,
) -> bpy.types.Action:
    """Obj's action, made and keyed at shown_before with what obj and its shear parent show if it has none."""
    action_identity = object_identity._replace(role=manifests.RepresentationRole.ACTION)
    if action_identity in keys:
        action = None if obj.animation_data is None else obj.animation_data.action
        assert action is not None  # made for it when a time code was first cached
        return action
    action_key = keys[action_identity] = manifests.new_entry_key()
    action = bpy.data.actions.new(obj.name)
    work.track(action_key, manifests.RepresentationRole.ACTION, action)
    entry = published.entries[object_key]
    changes[action_key] = manifests.ManifestEntryChange(
        entry.source_entity_paths, manifests.RepresentationRole.ACTION, [], entry.object_index_in_copy
    )
    for owner, owner_key in _with_shear_parent(obj, object_key, published):
        work.rollback_actions.append(owner.animation_data_clear)  # a copy's objects have none before its first action
        owner.animation_data_create().action = action
        _key_transform(action, owner, shown_before, owner.matrix_basis.copy(), work)
        _use(owner_key, action_key, published, changes)
    _key_hide_flags(action, obj, shown_before, (obj.hide_viewport, obj.hide_render), work)
    return action


def _with_shear_parent(
    obj: bpy.types.Object, object_key: str, published: manifests.Manifest
) -> list[tuple[bpy.types.Object, str]]:
    """Obj and its published shear parent, if it has one, each with its entry key."""
    found = [(obj, object_key)]
    if (parent := obj.parent) is not None:
        [parent_key] = [k for k, e in published.entries.items() if e.datablock == parent]
        found.append((parent, parent_key))
    return found


def _new_shear_parent(  # noqa: PLR0913 - the object, its parent's identity, and the call's state
    obj: bpy.types.Object,
    parent_identity: manifests.CopyResourceIdentity,
    object_and_action_keys: tuple[str, str],
    keys: dict[manifests.CopyResourceIdentity, str],
    published: manifests.Manifest,
    destination: bpy.types.Collection,
    names: application.ManagedNames,
    changes: dict[str, manifests.ManifestEntryChange],
    work: PreparationResources,
) -> bpy.types.Object:
    """A shear parent for obj, identity, made, held in work, linked into destination, and assigned obj's action.

    object_and_action_keys are the entry keys of obj and of its action.
    """
    object_key, action_key = object_and_action_keys
    parent_key = keys[parent_identity] = manifests.new_entry_key()
    parent = bpy.data.objects.new(names.next_name(f"{parent_identity.entity.rsplit('/', 1)[-1]} shear"), None)
    work.track(parent_key, parent_identity.role, parent)
    parent.hide_select = True  # so a pick lands on the object, as preparation's
    work.rollback_actions.append(functools.partial(destination.objects.unlink, parent))
    destination.objects.link(parent)
    basis = obj.matrix_basis.copy()
    work.rollback_actions.append(functools.partial(_unparent, obj, basis))
    obj.parent = parent
    obj.matrix_basis = basis  # the parent is the identity, so obj shows what it showed
    action = obj.animation_data.action if obj.animation_data is not None else None
    assert action is not None  # the copy's, made first
    parent.animation_data_create().action = action
    entry = published.entries[object_key]
    changes[parent_key] = manifests.ManifestEntryChange(
        entry.source_entity_paths, parent_identity.role, [action_key], parent_identity.object_index_in_copy
    )
    _use(object_key, parent_key, published, changes)
    return parent


def _unparent(obj: bpy.types.Object, basis: Matrix) -> None:
    obj.parent = None
    obj.matrix_basis = basis


def _use(
    user_key: str, used_key: str, published: manifests.Manifest, changes: dict[str, manifests.ManifestEntryChange]
) -> None:
    """Make the entry under user_key, as changes or published hold it, use the entry under used_key too."""
    entry = changes.get(user_key) or published.entries[user_key]
    changes[user_key] = manifests.ManifestEntryChange(
        entry.source_entity_paths, entry.role, [*entry.dependency_entry_keys, used_key], entry.object_index_in_copy
    )


def _key_transform(
    action: bpy.types.Action,
    owner: bpy.types.Object,
    time_codes: Iterable[float],
    basis: Matrix,
    work: PreparationResources,
) -> None:
    """Key owner's transform in action at each of time_codes to basis, constant until its next key, undoably."""
    location, rotation, scale = basis.decompose()
    # Slices, since the stubs don't make a Vector iterable; a copy's objects keep the default rotation mode.
    parts = {"location": location[:], "rotation_euler": rotation.to_euler("XYZ")[:], "scale": scale[:]}
    for time_code in time_codes:
        for data_path, values in parts.items():
            for index, value in enumerate(values):
                _insert_key(action, owner, data_path, index, time_code, value, work)


def _key_hide_flags(
    action: bpy.types.Action,
    obj: bpy.types.Object,
    time_codes: Iterable[float],
    hidden: tuple[bool, bool],
    work: PreparationResources,
) -> None:
    """Key obj's hide flags in action at each of time_codes, viewport's then render's, undoably."""
    for time_code in time_codes:
        for flag, value in zip(_HIDE_FLAGS, hidden, strict=True):
            _insert_key(action, obj, flag, 0, time_code, float(value), work)


def _insert_key(  # noqa: PLR0913 - the channel, and its key
    action: bpy.types.Action,
    owner: bpy.types.Object,
    data_path: str,
    index: int,
    time_code: float,
    value: float,
    work: PreparationResources,
) -> None:
    """Key owner's data_path[index] in action at time_code to value, constant until its next key, undoably in work."""
    fcurve = action.fcurve_ensure_for_datablock(owner, data_path, index=index)
    work.rollback_actions.append(
        functools.partial(_remove_key, fcurve, time_code)
    )  # before, so a failed insert is undone
    fcurve.keyframe_points.insert(time_code, value, options={"FAST"}).interpolation = "CONSTANT"


def _remove_key(fcurve: bpy.types.FCurve, time_code: float) -> None:
    """Remove fcurve's key at time_code, if it has one."""
    points = fcurve.keyframe_points
    if (point := next((p for p in points if p.co[0] == time_code), None)) is not None:
        points.remove(point)
