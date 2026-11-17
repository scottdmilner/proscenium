"""Keying the published display at a cache call's time codes (pipeline.md#cached-time-codes; M7 plan, D1 to D3).

key_time_codes keys each published copy that varies at every time code the call caches: its object's transform and
hide flags, and, when the plan splits its world transform at a time code, its shear parent's world transform and its
object's basis below it. A copy's object and its shear parent share one action, each through a slot of its own, so a
copy's action has one identity, its object's with the action's role. Keys are constant, so a frame shows the latest
key at or before it. A copy whose bounds vary has its bounds mesh's corners at each time code as a position sample,
which a frames modifier first in its object's stack shows for the sample its keyed Sample input names
(attribute_samples); every such modifier shows the display's one frames group, a shared node group.

A copy keyed for the first time gets its action, made and held in the prepared work, keyed at the generation's own time
code and at the time codes cached before with what its object and shear parent show, which they showed there, since they
weren't keyed; one whose bounds are first sampled shows its mesh's own positions there. A copy the plan draws only at a
cached time code has its partition made, as preparation makes one, and linked into the destination, keyed hidden where
the generation showed itself; a copy a plan lacks is keyed hidden at that time code. A copy sheared at a cached time
code but not at the generation's own gets a shear parent, made, held, and linked into the destination, identity at the
time codes it isn't sheared at; a copy sheared at its own but not at a cached time code keeps its parent, identity
there. Each change to a published resource has its undo in the prepared work before it's made, so a failing call removes
the keys and samples it added and the modifiers it made, unparents and unlinks what it parented, and its prepared work
is disposed of (CACHE-03).
"""

from __future__ import annotations

import contextlib
import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy
from mathutils import Matrix

from proscenium_sync.binding_persistence import manifests

from . import application, attribute_samples

if TYPE_CHECKING:
    from collections.abc import Buffer, Callable, Collection, Iterable, Mapping, Sequence

    from proscenium_sync import core

    from .preparation_resources import PreparationResources

_NO_SHEAR = -1  # in the plan's copy_shear_split_indices: the copy's world transform isn't split
_HIDE_FLAGS = ("hide_viewport", "hide_render")
_POSITION, _POSITION_TYPE, _POSITION_DOMAIN = attribute_samples.POSITIONS[0]


@dataclass(frozen=True, slots=True)
class VaryingCopies:
    """The copies a cache call keys, by source entity; None for every copy."""

    sources: Collection[str] | None


@dataclass(frozen=True, slots=True)
class _PlanViews:
    """Views of the plan buffers keying reads, released with the time code's keying (SNAP-13)."""

    plan: core.Plan
    shears: memoryview
    shear_parents: memoryview  # each copy's shear parent's resource index, or -1
    worlds: memoryview
    parent_worlds: memoryview
    bases: memoryview
    viewport: memoryview
    render: memoryview


def key_time_codes(  # noqa: PLR0913 - the plans, what they key, and the generation they key
    plans: Mapping[float, core.Plan],
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
        self, time_code: float, plan: core.Plan, varying: VaryingCopies, view: Callable[[Buffer], memoryview]
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
        resources = plan.resources_at(objects.tolist())
        present = {resource.source_entity_path for resource in resources}
        copies = [
            (copy, resource)
            for copy, resource in enumerate(resources)
            if varying.sources is None or resource.source_entity_path in varying.sources
        ]
        bounds = application.local_bounds(plan, [c for c, _ in copies], view)
        for copy, resource in copies:
            identity = manifests.CopyResourceIdentity(
                manifests.RepresentationRole(resource.role), resource.source_entity_path, resource.object_index_in_copy
            )
            appeared = identity not in self.keys
            if appeared:  # a copy the generation lacks, which appears here: its partition, made
                self._build_copy(plan, copy)
            object_key = self.keys[identity]
            obj = self.datablock(object_key)
            if obj is None:  # the user deleted it; the next synchronization replaces it
                continue
            assert isinstance(obj, bpy.types.Object)
            action = self._ensure_action(obj, identity, object_key)
            if appeared:  # it didn't exist where the generation showed itself
                _key_hide_flags(action, obj, self.shown_before, (True, True), self.work)
            # The copy's object of the form the plan draws it in at time_code, a box or a marker, and the other's.
            shown, other = self._forms(obj, identity, object_key, action, bounds[copy])
            self._key_copy(time_code, views, copy, (obj, identity, object_key), action, (shown, other))
            if bounds[copy]:  # a box, whose bounds may differ from its mesh's
                shown_key = object_key if shown is obj else self.keys[identity._replace(object_index_in_copy=1)]
                self._key_bounds(time_code, shown, shown_key, action, bounds[copy])
        self._hide_absent(time_code, present, varying)

    def _build_copy(self, plan: core.Plan, copy: int) -> None:
        """Make plan's copy's partition as preparation does, held in the prepared work, linked into the destination."""
        made_before = set(self.work.manifest_entries)
        application.prepare(plan, [copy], self.published, self.work, self.names)
        for key, entry in self.work.manifest_entries.items():
            if key in made_before:
                continue
            assert entry.identity is not None  # a copy's resource
            self.keys[entry.identity] = key
            self.changes[key] = manifests.ManifestEntryChange(
                entry.source_entity_paths, entry.role, entry.dependency_entry_keys, entry.object_index_in_copy
            )
            if isinstance(made := entry.datablock, bpy.types.Object):
                self.work.rollback_actions.append(functools.partial(self.destination.objects.unlink, made))
                self.destination.objects.link(made)

    def _hide_absent(self, time_code: float, present: Collection[str], varying: VaryingCopies) -> None:
        """Key hidden at time_code each varying copy's objects whose copy the plan there lacks."""
        for identity, key in list(self.keys.items()):
            if identity.role is not manifests.RepresentationRole.OBJECT or identity.object_index_in_copy != 0:
                continue
            if identity.entity in present or (varying.sources is not None and identity.entity not in varying.sources):
                continue
            obj = self.datablock(key)
            if not isinstance(obj, bpy.types.Object):  # the user deleted it
                continue
            action = self._ensure_action(obj, identity, key)
            other_key = self.keys.get(identity._replace(object_index_in_copy=1))
            for form in (obj, None if other_key is None else self.datablock(other_key)):
                if isinstance(form, bpy.types.Object):
                    _key_hide_flags(action, form, (time_code,), (True, True), self.work)

    def _forms(
        self,
        obj: bpy.types.Object,
        identity: manifests.CopyResourceIdentity,
        object_key: str,
        action: bpy.types.Action,
        bounds: Sequence[float],
    ) -> tuple[bpy.types.Object, bpy.types.Object | None]:
        """The copy's object of the form bounds draw it in, and its other form's object, or None for none.

        A placeholder is a box with bounds and a marker without; obj is the form the generation drew. The other form's
        object is made the first time bounds call for it, with bounds' corners if a box.
        """
        other_identity = identity._replace(object_index_in_copy=1)
        other_key = self.keys.get(other_identity)
        other = None if other_key is None else self.datablock(other_key)
        assert other is None or isinstance(other, bpy.types.Object)  # a copy's object
        if isinstance(obj.data, bpy.types.Mesh) == bool(bounds):
            return obj, other
        if other is None:
            other = _new_other_form(self, obj, (identity, object_key), action, bounds)
        return other, obj

    def entry(self, entry_key: str) -> manifests.ManifestEntry | manifests.ManifestEntryChange:
        """The entry under entry_key, as this call changed or made it, else as published."""
        return self.changes.get(entry_key) or self.published.entries[entry_key]

    def key_of(self, datablock: bpy.types.ID) -> str:
        """The entry key of datablock, made by this call or published."""
        [key] = [k for k, d in self.work.datablocks.items() if d == datablock] or [
            k for k, e in self.published.entries.items() if e.datablock == datablock
        ]
        return key

    def datablock(self, entry_key: str) -> bpy.types.ID | None:
        """The datablock under entry_key, made by this call or published."""
        made = self.work.datablocks.get(entry_key)
        return made if made is not None else self.published.entries[entry_key].datablock

    def _key_copy(  # noqa: PLR0913 - the plan's copy, its published object, and its forms' objects
        self,
        time_code: float,
        views: _PlanViews,
        copy: int,
        published_object: tuple[bpy.types.Object, manifests.CopyResourceIdentity, str],
        action: bpy.types.Action,
        forms: tuple[bpy.types.Object, bpy.types.Object | None],
    ) -> None:
        """Key copy's transform and hide flags at time_code as views' plan shows them, with a shear parent if needed.

        forms are the object of the form the plan draws, which shows the plan's hide flags, and the other form's, which
        is hidden, or None; both take the copy's transform.
        """
        obj, identity, object_key = published_object
        shown, other = forms
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
        for form in (shown, other):
            if form is not None:
                _key_transform(action, form, (time_code,), basis, self.work)
        if parent is not None:
            _key_transform(action, parent, (time_code,), parent_world, self.work)
        _key_hide_flags(action, shown, (time_code,), (not views.viewport[copy], not views.render[copy]), self.work)
        if other is not None:
            _key_hide_flags(action, other, (time_code,), (True, True), self.work)

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
        entry = self.entry(object_key)
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
            parent_key = self.key_of(parent)
            found.append((parent, parent_key))
        return found

    def _key_bounds(  # noqa: PLR0913 - the copy's object and its bounds at the time code
        self,
        time_code: float,
        obj: bpy.types.Object,
        object_key: str,
        action: bpy.types.Action,
        bounds: Sequence[float],
    ) -> None:
        """Key obj's bounds mesh to show bounds' corners at time_code, undoably.

        Bounds equal to the mesh's own need nothing until it has samples, and are its own sample, BASE, after; others
        are added as a sample.
        """
        mesh = obj.data
        assert isinstance(mesh, bpy.types.Mesh)
        path = attribute_samples.sample_input_path()
        own = _corners(obj) == application.corners(bounds)
        sampled = obj.modifiers.get(attribute_samples.MODIFIER) is not None
        if own:
            if sampled:
                _insert_key(action, obj, path, 0, time_code, attribute_samples.BASE, self.work)
            return
        if not sampled:
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
        entry = self.entry(user_key)
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
    entry = call.entry(object_key)
    call.changes[parent_key] = manifests.ManifestEntryChange(
        entry.source_entity_paths, parent_identity.role, [action_key], parent_identity.object_index_in_copy
    )
    call.use(object_key, parent_key)
    return parent


def _new_other_form(
    call: _CallKeying,
    obj: bpy.types.Object,
    published_object: tuple[manifests.CopyResourceIdentity, str],
    action: bpy.types.Action,
    bounds: Sequence[float],
) -> bpy.types.Object:
    """The copy's object of the form obj isn't, made, held, linked, and keyed hidden where obj showed itself.

    A box, with bounds' corners in its bounds mesh, if obj is a marker, else a marker. It takes obj's parent, place 1
    among the copy's objects, and the copy's action.
    """
    identity, object_key = published_object
    name = call.names.next_name(identity.entity.rsplit("/", 1)[-1])
    other_identity = identity._replace(object_index_in_copy=1)
    other_key = call.keys[other_identity] = manifests.new_entry_key()
    entry = call.entry(object_key)
    uses = [call.keys[identity._replace(role=manifests.RepresentationRole.ACTION)]]
    mesh = None
    if bounds:  # a box
        mesh_identity = other_identity._replace(role=manifests.RepresentationRole.BOUNDS_MESH)
        mesh_key = call.keys[mesh_identity] = manifests.new_entry_key()
        mesh = bpy.data.meshes.new(name)
        call.work.track(mesh_key, mesh_identity.role, mesh)
        mesh.from_pydata(application.corners(bounds), [], [])
        call.changes[mesh_key] = manifests.ManifestEntryChange(entry.source_entity_paths, mesh_identity.role, [], 1)
        uses.append(mesh_key)
    other = bpy.data.objects.new(name, mesh)
    call.work.track(other_key, other_identity.role, other)
    other.display_type = "BOUNDS"
    call.work.rollback_actions.append(functools.partial(call.destination.objects.unlink, other))
    call.destination.objects.link(other)
    if (parent := obj.parent) is not None:
        other.parent = parent
        parent_key = call.key_of(parent)
        uses.append(parent_key)
    other.matrix_basis = obj.matrix_basis.copy()
    other.animation_data_create().action = action
    _key_transform(action, other, call.shown_before, other.matrix_basis.copy(), call.work)
    _key_hide_flags(action, other, call.shown_before, (True, True), call.work)
    call.changes[other_key] = manifests.ManifestEntryChange(entry.source_entity_paths, other_identity.role, uses, 1)
    return other


def _corners(obj: bpy.types.Object) -> list[tuple[float, float, float]]:
    """The corners obj's bounds mesh holds, as application.corners orders them."""
    mesh = obj.data
    assert isinstance(mesh, bpy.types.Mesh)
    return [tuple(v.co[:]) for v in mesh.vertices]  # ty: ignore[invalid-return-type] - three floats each


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
