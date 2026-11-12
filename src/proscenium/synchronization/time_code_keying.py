"""Keying the published display at a cache call's time codes (pipeline.md#cached-time-codes; M7 plan, D1 to D3).

key_time_codes keys each published copy that varies at every time code the call caches: its object's transform and
hide flags, and, when the plan splits its world transform at a time code, its shear parent's world transform and its
object's basis below it. A copy's object and its shear parent share one action, each through a slot of its own, so a
copy's action has one identity, its object's with the action's role. Keys are constant, so a frame shows the latest
key at or before it. A copy whose bounds vary has its bounds mesh's corners at each time code as a position sample,
which a frames modifier first in its object's stack shows for the sample its keyed Sample input names
(attribute_samples); every such modifier shows the display's one frames group, a shared node group.

A copy keyed for the first time gets its action, made and held in the prepared work, keyed at the generation's own
time code and at the time codes cached before with what its object and shear parent show, which they showed there,
since they weren't keyed; one whose bounds are first sampled shows its mesh's own positions there. A copy sheared at a
cached time code but not at the generation's own gets a shear parent, made, held, and linked into the destination,
identity at the time codes it isn't sheared at; a copy sheared at its own but not at a cached time code keeps its
parent, identity there. Each change to a published resource has its undo in the prepared work before it's made, so a
failing call removes the keys and samples it added and the modifiers it made, unparents and unlinks what it parented,
and its prepared work is disposed of (CACHE-03).
"""

from __future__ import annotations

import contextlib
import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy
from mathutils import Matrix

from ..binding.persistence import manifests
from . import application, attribute_samples

if TYPE_CHECKING:
    from collections.abc import Buffer, Callable, Collection, Iterable, Mapping, Sequence

    from ..core import _core
    from .preparation_resources import PreparationResources

_NO_SHEAR = -1  # in the plan's copy_shear_split_indices: the copy's world transform isn't split
_HIDE_FLAGS = ("hide_viewport", "hide_render")
_POSITION, _POSITION_TYPE, _POSITION_DOMAIN = attribute_samples.POSITIONS[0]


@dataclass(frozen=True, slots=True)
class VaryingCopies:
    """The copies a cache call keys, by source entity; None for every copy."""

    sources: Collection[str] | None  # keyed for their transforms and hide flags
    bounds_sources: Collection[str] | None  # and for their bounds, among them


@dataclass(frozen=True, slots=True)
class _PlanViews:
    """Views of the plan buffers keying reads, released with the time code's keying (SNAP-13)."""

    plan: _core.Plan
    shears: memoryview
    shear_parents: memoryview  # each copy's shear parent's resource index, or -1
    worlds: memoryview
    parent_worlds: memoryview
    bases: memoryview
    viewport: memoryview
    render: memoryview


def key_time_codes(  # noqa: PLR0913 - the plans, what they key, and the generation they key
    plans: Mapping[float, _core.Plan],
    varying: VaryingCopies,
    published: manifests.Manifest,
    destination: bpy.types.Collection,
    own: float,
    cached_before: Sequence[float],
    work: PreparationResources,
) -> dict[str, manifests.ManifestEntryChange]:
    """Key each published copy varying names at each of plans' time codes; the manifest changes it makes.

    destination holds published, the generation's manifest, published at own and cached at cached_before. The changes
    are each new action's, shear parent's, and frames group's entry, and the entries that use them. A copy the
    published generation lacks, as one appearing only at a cached time code, is Phase D's. Raises whatever Blender
    raises.
    """
    call = _CallKeying(published, destination, (own, *cached_before), work)
    for time_code, plan in plans.items():
        with contextlib.ExitStack() as views:  # each view released on return or raise (SNAP-13)

            def view(buffer: Buffer) -> memoryview:
                return views.enter_context(memoryview(buffer))

            call.key_plan(time_code, plan, varying, view)
    return call.changes


class _CallKeying:
    """One cache call's keying: the published generation's, and the manifest changes so far."""

    published: manifests.Manifest
    destination: bpy.types.Collection
    shown_before: Sequence[float]  # the generation's own time code and those cached before
    work: PreparationResources
    keys: dict[manifests.CopyResourceIdentity, str]  # each copy's resource's entry key, made ones included
    changes: dict[str, manifests.ManifestEntryChange]
    names: application.ManagedNames
    frames_group_key: str | None  # the frames group's entry key, once found or made

    def __init__(
        self,
        published: manifests.Manifest,
        destination: bpy.types.Collection,
        shown_before: Sequence[float],
        work: PreparationResources,
    ) -> None:
        self.published, self.destination, self.shown_before, self.work = published, destination, shown_before, work
        self.keys = {identity: key for key, e in published.entries.items() if (identity := e.identity) is not None}
        self.changes = {}
        self.names = application.ManagedNames()
        groups = [k for k, e in published.entries.items() if e.role is manifests.RepresentationRole.NODE_GROUP]
        self.frames_group_key = groups[0] if groups else None  # M7's one shared node group

    def key_plan(
        self, time_code: float, plan: _core.Plan, varying: VaryingCopies, view: Callable[[Buffer], memoryview]
    ) -> None:
        """Key the copies varying names at time_code, as plan shows them; view opens a view of its buffers."""
        views = _PlanViews(
            plan,
            view(plan.copy_shear_split_indices),
            view(plan.copy_shear_parent_resource_indices),
            view(plan.copy_world_matrices),
            view(plan.shear_parent_world_matrices),
            view(plan.shear_object_basis_matrices),
            view(plan.copy_visible_in_viewport),
            view(plan.copy_visible_in_render),
        )
        objects = view(plan.copy_object_resource_indices)
        copies = [
            (copy, resource)
            for copy, resource in enumerate(plan.resources_at(objects.tolist()))
            if varying.sources is None or resource.source_entity_path in varying.sources
        ]
        sampled = [
            c for c, r in copies if varying.bounds_sources is None or r.source_entity_path in varying.bounds_sources
        ]
        bounds = application.local_bounds(plan, sampled, view)
        for copy, resource in copies:
            identity = manifests.CopyResourceIdentity(
                manifests.RepresentationRole(resource.role), resource.source_entity_path, resource.object_index_in_copy
            )
            if (object_key := self.keys.get(identity)) is None:
                continue  # one the generation lacks
            obj = self.published.entries[object_key].datablock
            if obj is None:  # the user deleted it; the next synchronization replaces it
                continue
            assert isinstance(obj, bpy.types.Object)
            action = self._ensure_action(obj, identity, object_key)
            self._key_copy(time_code, views, copy, (obj, identity, object_key), action)
            if copy in bounds and bounds[copy] and isinstance(obj.data, bpy.types.Mesh):
                self._sample_bounds(time_code, obj, object_key, action, bounds[copy])

    def _key_copy(
        self,
        time_code: float,
        views: _PlanViews,
        copy: int,
        published_object: tuple[bpy.types.Object, manifests.CopyResourceIdentity, str],
        action: bpy.types.Action,
    ) -> None:
        """Key copy's transform and hide flags at time_code as views' plan shows them, with a shear parent if needed."""
        obj, identity, object_key = published_object
        shear, parent = views.shears[copy], obj.parent
        if shear != _NO_SHEAR and parent is None:
            [parent_resource] = views.plan.resources_at([views.shear_parents[copy]])
            parent_identity = manifests.CopyResourceIdentity(
                manifests.RepresentationRole.SHEAR_PARENT, identity.entity, parent_resource.object_index_in_copy
            )
            action_key = self.keys[identity._replace(role=manifests.RepresentationRole.ACTION)]
            parent = _new_shear_parent(self, obj, parent_identity, (object_key, action_key))
            _key_transform(action, parent, self.shown_before, Matrix.Identity(4), self.work)
        if shear != _NO_SHEAR:
            assert parent is not None
            parent_world = application.matrix_from_buffer(views.parent_worlds, shear)
            basis = application.matrix_from_buffer(views.bases, shear)
        else:
            parent_world, basis = Matrix.Identity(4), application.matrix_from_buffer(views.worlds, copy)
        _key_transform(action, obj, (time_code,), basis, self.work)
        if parent is not None:
            _key_transform(action, parent, (time_code,), parent_world, self.work)
        hidden = (not views.viewport[copy], not views.render[copy])
        _key_hide_flags(action, obj, (time_code,), hidden, self.work)

    def _ensure_action(
        self, obj: bpy.types.Object, object_identity: manifests.CopyResourceIdentity, object_key: str
    ) -> bpy.types.Action:
        """Obj's action, made and keyed at shown_before with what obj and its shear parent show if it has none."""
        action_identity = object_identity._replace(role=manifests.RepresentationRole.ACTION)
        if action_identity in self.keys:
            action = None if obj.animation_data is None else obj.animation_data.action
            assert action is not None  # made for it when a time code was first cached
            return action
        action_key = self.keys[action_identity] = manifests.new_entry_key()
        action = bpy.data.actions.new(obj.name)
        self.work.track(action_key, manifests.RepresentationRole.ACTION, action)
        entry = self.published.entries[object_key]
        self.changes[action_key] = manifests.ManifestEntryChange(
            entry.source_entity_paths, manifests.RepresentationRole.ACTION, [], entry.object_index_in_copy
        )
        for owner, owner_key in self._with_shear_parent(obj, object_key):
            # A copy's objects have no animation data before its first action.
            self.work.rollback_actions.append(owner.animation_data_clear)
            owner.animation_data_create().action = action
            _key_transform(action, owner, self.shown_before, owner.matrix_basis.copy(), self.work)
            self.use(owner_key, action_key)
        _key_hide_flags(action, obj, self.shown_before, (obj.hide_viewport, obj.hide_render), self.work)
        return action

    def _with_shear_parent(self, obj: bpy.types.Object, object_key: str) -> list[tuple[bpy.types.Object, str]]:
        """Obj and its published shear parent, if it has one, each with its entry key."""
        found = [(obj, object_key)]
        if (parent := obj.parent) is not None:
            [parent_key] = [k for k, e in self.published.entries.items() if e.datablock == parent]
            found.append((parent, parent_key))
        return found

    def _sample_bounds(  # noqa: PLR0913 - the copy's object and its bounds at the time code
        self,
        time_code: float,
        obj: bpy.types.Object,
        object_key: str,
        action: bpy.types.Action,
        bounds: Sequence[float],
    ) -> None:
        """Add bounds' corners at time_code as a sample of obj's bounds mesh, keyed shown there, undoably."""
        mesh = obj.data
        assert isinstance(mesh, bpy.types.Mesh)
        path = attribute_samples.sample_input_path()
        if obj.modifiers.get(attribute_samples.MODIFIER) is None:
            group = self._ensure_frames_group()
            self.work.rollback_actions.append(functools.partial(_remove_frames_modifier, obj))
            attribute_samples.new_frames_modifier(obj, group)
            assert self.frames_group_key is not None
            self.use(object_key, self.frames_group_key)
            for shown_at in self.shown_before:  # its own positions, as it showed them
                _insert_key(action, obj, path, 0, shown_at, attribute_samples.BASE, self.work)
        sample = attribute_samples.sample_count(mesh, _POSITION)
        values = [value for corner in application.corners(bounds) for value in corner]
        sample_name = f"{_POSITION}{attribute_samples.FRAME_SEPARATOR}{sample}"
        self.work.rollback_actions.append(functools.partial(attribute_samples.remove_attribute, mesh, sample_name))
        attribute_samples.add_sample(mesh, _POSITION, _POSITION_TYPE, _POSITION_DOMAIN, values)
        _insert_key(action, obj, path, 0, time_code, sample, self.work)

    def _ensure_frames_group(self) -> bpy.types.NodeTree:
        """The display's frames group, made and held in the prepared work if it has none."""
        if self.frames_group_key is not None:
            made = self.work.datablocks.get(self.frames_group_key)
            group = made if made is not None else self.published.entries[self.frames_group_key].datablock
            assert isinstance(group, bpy.types.NodeTree)
            return group
        key = self.frames_group_key = manifests.new_entry_key()
        group = attribute_samples.new_frames_group(attribute_samples.POSITIONS)
        self.work.track(key, manifests.RepresentationRole.NODE_GROUP, group)
        self.changes[key] = manifests.ManifestEntryChange([], manifests.RepresentationRole.NODE_GROUP, [])
        return group

    def use(self, user_key: str, used_key: str) -> None:
        """Make the entry under user_key, as changes or published hold it, use the entry under used_key too."""
        entry = self.changes.get(user_key) or self.published.entries[user_key]
        self.changes[user_key] = manifests.ManifestEntryChange(
            entry.source_entity_paths, entry.role, [*entry.dependency_entry_keys, used_key], entry.object_index_in_copy
        )


def _new_shear_parent(
    call: _CallKeying,
    obj: bpy.types.Object,
    parent_identity: manifests.CopyResourceIdentity,
    object_and_action_keys: tuple[str, str],
) -> bpy.types.Object:
    """A shear parent for obj, identity, made, held, linked into the call's destination, and assigned obj's action.

    object_and_action_keys are the entry keys of obj and of its action.
    """
    object_key, action_key = object_and_action_keys
    parent_key = call.keys[parent_identity] = manifests.new_entry_key()
    parent = bpy.data.objects.new(call.names.next_name(f"{parent_identity.entity.rsplit('/', 1)[-1]} shear"), None)
    call.work.track(parent_key, parent_identity.role, parent)
    parent.hide_select = True  # so a pick lands on the object, as preparation's
    call.work.rollback_actions.append(functools.partial(call.destination.objects.unlink, parent))
    call.destination.objects.link(parent)
    basis = obj.matrix_basis.copy()
    call.work.rollback_actions.append(functools.partial(_unparent, obj, basis))
    obj.parent = parent
    obj.matrix_basis = basis  # the parent is the identity, so obj shows what it showed
    action = obj.animation_data.action if obj.animation_data is not None else None
    assert action is not None  # the copy's, made first
    parent.animation_data_create().action = action
    entry = call.published.entries[object_key]
    call.changes[parent_key] = manifests.ManifestEntryChange(
        entry.source_entity_paths, parent_identity.role, [action_key], parent_identity.object_index_in_copy
    )
    call.use(object_key, parent_key)
    return parent


def _unparent(obj: bpy.types.Object, basis: Matrix) -> None:
    obj.parent = None
    obj.matrix_basis = basis


def _remove_frames_modifier(obj: bpy.types.Object) -> None:
    if (modifier := obj.modifiers.get(attribute_samples.MODIFIER)) is not None:
        obj.modifiers.remove(modifier)


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
    # Before, so a failed insert is undone.
    work.rollback_actions.append(functools.partial(_remove_key, fcurve, time_code))
    fcurve.keyframe_points.insert(time_code, value, options={"FAST"}).interpolation = "CONSTANT"


def _remove_key(fcurve: bpy.types.FCurve, time_code: float) -> None:
    """Remove fcurve's key at time_code, if it has one."""
    points = fcurve.keyframe_points
    if (point := next((p for p in points if p.co[0] == time_code), None)) is not None:
        points.remove(point)
