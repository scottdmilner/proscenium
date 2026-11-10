"""M5's stub application layer: each drawn copy as its bounds, prepared apart (pipeline.md#blender-application).

Each of the plan's drawn copies becomes an object drawing its bounding box and the bounds mesh it draws: the eight
corners of its local bounds, a mesh's provisional geometry description's or a placeholder's, or no vertices when the
plan has none. An empty marker's object holds no data. Each object is hidden in each destination it doesn't display
in, and a sheared copy's sits under an unselectable empty, its shear parent. Objects and their bounds meshes are named
so each lands at the end of Blender's sorted lists (_MANAGED_NAME). They're prepared in a staging collection no scene
links, so nothing prepared is visible, and preparation only creates datablocks: it never changes one the published
generation reaches (TXN-05). Each is held in the prepared work as soon as it exists (prepared_work).

The roles are a copy's, so each prepared resource takes the key of the published entry with its identity, or a new one
(manifests.entry_keys), and the entries preparation makes are the manifest a publication writes.

A cache call has it key the published copies' transforms at the time codes it caches, in an action per object
(key_time_codes), holding how to undo each change in the prepared work first, so a failing call removes the keys it
added and unassigns the actions it made. M7 replaces this layer; a shear that changes over time is M7's, as are
cached bounds, visibility, and content appearing at a cached time code.
"""

from __future__ import annotations

import functools
import itertools
import re
from typing import TYPE_CHECKING

import bpy
from mathutils import Matrix

from ..binding.persistence import manifests

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ..core import _core
    from .prepared_work import PreparationResources

# A managed object's name, which its bounds mesh shares: a tilde, which sorts after ASCII letters, digits, and most
# punctuation, then its generation and its ordinal in the plan's order, zero-padded, then its prim's name, so each lands
# at the end of Blender's sorted lists (DECISIONS.md "Managed object names").
_MANAGED_NAME = re.compile(r"~(\d{6})\.\d{7} ")

REPRESENTATION_VERSION = 1  # the representation this layer applies, which the planning context names


def prepare(plan: _core.Plan, published: manifests.Manifest, work: PreparationResources) -> None:
    """Make plan's drawn copies in work's staging collection, holding each datablock as it's made (TXN-08).

    published is the binding's published manifest, whose entries' keys the prepared resources with their identities
    take. Raises whatever Blender raises; what was made before stays in work, held.
    """
    resources = plan.resources  # each read builds the tuple anew
    identities = [
        manifests.CopyResourceIdentity(manifests.RepresentationRole(r.role), r.entity, r.place) for r in resources
    ]
    keys = manifests.entry_keys(published, identities)
    worlds, bounds = memoryview(plan.copy_worlds), _bounds(plan)
    viewport, render = memoryview(plan.copy_viewport).tolist(), memoryview(plan.copy_render).tolist()
    shears = memoryview(plan.copy_shears).tolist()
    parent_worlds, bases = memoryview(plan.shear_parent_worlds), memoryview(plan.shear_object_bases)
    # Objects, and their bounds meshes, are named in the plan's order after a new generation (DECISIONS.md "Managed
    # object names").
    prefix, ordinals = f"~{_next_object_generation_number():06d}.", itertools.count()
    # Each staged object's hide flags, in the order linked, set together after the loop: assigning one runs Blender's
    # update, which resyncs every collection, at a cost that grows with the scene (34.7 s for 30,000 objects beside a
    # published display of as many, ad hoc).
    hidden: dict[str, list[bool]] = {"hide_viewport": [], "hide_render": []}
    for copy, object_index in enumerate(memoryview(plan.copy_objects).tolist()):
        # The object's uses: its bounds mesh, but for an empty marker's, and a sheared copy's shear parent.
        used = {identities[u].role: u for u in resources[object_index].uses}
        object_key = keys[object_index]
        source = resources[object_index].entity
        name = source.rsplit("/", 1)[-1]
        made: list[tuple[int, str, bpy.types.ID]] = []
        object_name = f"{prefix}{next(ordinals):07d} {name}"
        mesh = None
        if (mesh_index := used.get(manifests.RepresentationRole.BOUNDS_MESH)) is not None:
            mesh = bpy.data.meshes.new(object_name)
            work.track(keys[mesh_index], identities[mesh_index].role, mesh)
            mesh.from_pydata(_corners(bounds[copy]), [], [])
            made.append((mesh_index, keys[mesh_index], mesh))
        obj = bpy.data.objects.new(object_name, mesh)
        work.track(object_key, identities[object_index].role, obj)
        work.staging.objects.link(obj)
        made.append((object_index, object_key, obj))
        obj.display_type = "BOUNDS"
        hidden["hide_viewport"].append(not viewport[copy])
        hidden["hide_render"].append(not render[copy])
        if (shear := shears[copy]) < 0:
            obj.matrix_world = _matrix_from_buffer(worlds, copy)
        else:
            # Blender objects hold no shear, so the parent and the object each hold part, as the plan splits it.
            parent_index = used[manifests.RepresentationRole.SHEAR_PARENT]
            parent = bpy.data.objects.new(f"{prefix}{next(ordinals):07d} {name} shear", None)
            work.track(keys[parent_index], identities[parent_index].role, parent)
            work.staging.objects.link(parent)
            hidden["hide_viewport"].append(False)
            hidden["hide_render"].append(False)
            made.append((parent_index, keys[parent_index], parent))
            parent.hide_select = True  # so a pick lands on the object
            parent.matrix_world = _matrix_from_buffer(parent_worlds, shear)
            obj.parent = parent
            obj.matrix_basis = _matrix_from_buffer(bases, shear)
        for index, key, datablock in made:
            resource = resources[index]
            uses = [keys[used] for used in resource.uses]
            work.entries[key] = manifests.ManifestEntry(
                datablock, list(resource.covers), identities[index].role, uses, resource.place
            )
    for flag, values in hidden.items():
        work.staging.objects.foreach_set(flag, values)


def key_time_codes(
    plans: Mapping[float, _core.Plan], published: manifests.Manifest, own: float, work: PreparationResources
) -> dict[str, manifests.EntryChange]:
    """Key each published copy's transform at each of plans' time codes; the manifest changes it makes.

    Each change to a published object is undoable through work.undo. A copy's object first keyed gets an action, made
    and held in work, and is keyed at own, the generation's time code, as it shows it, too. Keys are constant, so a
    frame shows the latest key at or before it. The changes are each new action's entry, with its object's identity,
    and its object's, using it. A copy the published generation lacks, as one appearing only at a cached time code, is
    M7's. Raises whatever Blender raises.
    """
    keys = {identity: key for key, e in published.entries.items() if (identity := e.identity) is not None}
    changes: dict[str, manifests.EntryChange] = {}
    for time_code, plan in plans.items():
        resources = plan.resources  # each read builds the tuple anew
        worlds = memoryview(plan.copy_worlds)
        for copy, object_index in enumerate(memoryview(plan.copy_objects).tolist()):
            resource = resources[object_index]
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
            world = _matrix_from_buffer(worlds, copy)
            # Below a shear parent, the basis that shows world while the parent keeps its transform; a copy whose
            # shear changes over time is M7's.
            basis = world if obj.parent is None else obj.parent.matrix_world.inverted() @ world
            _insert_keys(action, obj, time_code, basis, work)
    return changes


def _new_action(obj: bpy.types.Object, action_key: str, own: float, work: PreparationResources) -> None:
    """Give obj an action, held in work under action_key, keyed at own with the transform obj shows."""
    action = bpy.data.actions.new(obj.name)
    work.track(action_key, manifests.RepresentationRole.ACTION, action)
    work.undo.append(obj.animation_data_clear)  # a copy's object has no animation data before its first action
    obj.animation_data_create().action = action
    _insert_keys(action, obj, own, obj.matrix_basis, work)


def _insert_keys(
    action: bpy.types.Action, obj: bpy.types.Object, time_code: float, basis: Matrix, work: PreparationResources
) -> None:
    """Key obj's transform in its action at time_code to basis, constant until its next key, undoably in work."""
    location, rotation, scale = basis.decompose()
    # Slices, since the stubs don't make a Vector iterable; a copy's object keeps the default rotation mode.
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


def _next_object_generation_number() -> int:
    """One more than the generation in the last managed object name, or 0 for none.

    Blender keeps its objects sorted by name, so the last is usually managed and found at once; a user object sorting
    after the managed ones is passed over.
    """
    for obj in reversed(bpy.data.objects):
        if match := _MANAGED_NAME.match(obj.name):
            return int(match.group(1)) + 1
    return 0


def _bounds(plan: _core.Plan) -> list[Sequence[float]]:
    """Each copy's local bounds as (min x, y, z, max x, y, z), or empty for none."""
    extents = [memoryview(g.extent).tolist() for g in plan.geometries]
    placeholder_bounds = memoryview(plan.placeholder_bounds).tolist()
    geometries = memoryview(plan.copy_geometries).tolist()
    placeholders = memoryview(plan.copy_placeholders).tolist()
    return [
        extents[g] if g >= 0 else placeholder_bounds[6 * p : 6 * p + 6] if p >= 0 else []
        for g, p in zip(geometries, placeholders, strict=True)
    ]


def _corners(bounds: Sequence[float]) -> list[tuple[float, float, float]]:
    """The eight corners of (min x, y, z, max x, y, z), or none for no bounds."""
    if not bounds:
        return []
    low, high = bounds[:3], bounds[3:]
    return [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]


def _matrix_from_buffer(matrices: memoryview, index: int) -> Matrix:
    """Matrix `index` of a plan's buffer of them, whose 16 floats each are Blender's column-major layout."""
    columns = matrices[16 * index : 16 * index + 16].tolist()
    return Matrix([columns[i : i + 4] for i in range(0, 16, 4)]).transposed()
