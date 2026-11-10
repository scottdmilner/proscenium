"""Update an applied display to a new plan from its diff (M4, B6 and C2): what an update costs in the object baseline.

The diff (diff_plans) says which of the published display's meshes, materials, and objects the new plan keeps.
Preparation builds the rest beside the display, in a collection no scene links, so it changes nothing the
display uses (TXN-05):
- each new mesh and material;
- each added object, and each changed one. Under repointing, a changed object that differs only in its mesh or
  materials is kept instead. With moves (M4 Phase E), so is one whose world matrix differs, if neither its old
  nor its new transform needs a shear parent, and under replacement, if it keeps its data.

Publication then makes the change in one call (TXN-06):
- it links the new objects in place of the old ones, and unlinks the removed ones;
- it moves the kept users of a rebuilt mesh or material onto it, and sets each kept moved object's matrix;
- it renumbers the kept objects whose plan index changed.

It undoes all of that if any step fails. Retirement removes the old objects, and the old meshes and materials
nothing uses once those are gone. One that something outside the display still uses is left intact (OWN-08).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import bpy
from apply import SHEAR_PARENT, Display, new_material, new_mesh, new_object, sheared, usd_matrix_to_blender
from selection import ELEMENT

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from mathutils import Matrix
    from plan_types import ObjectRecord, Plan, PlanDiff


class DependentObjectUpdatePolicy(StrEnum):
    """What happens to the objects that differ only in using a rebuilt mesh or material."""

    REPOINT = "repoint"  # they are kept, and publication moves them onto the rebuilt data
    REPLACE = "replace"  # they are replaced


@dataclass(frozen=True)
class DisplayRebuildSet:
    """The object, mesh, and material indices selected for rebuilding from an unchanged plan (unit_diff)."""

    object_indices: frozenset[int] = frozenset()
    mesh_indices: frozenset[int] = frozenset()
    material_indices: frozenset[int] = frozenset()


@dataclass
class ObjectResourceUpdate:
    """A kept object's data and slots, and its world matrix when it moved, as publication sets them."""

    mesh: Any  # the object's new mesh; Object.data is typed as every kind of object data
    material_slots: list[bpy.types.Material | None]
    world_matrix: Matrix | None = None  # Blender's world matrix, for a moved object


@dataclass
class PreparedDisplayUpdate:
    """An update built beside the published display, which it doesn't touch until publication."""

    # Where the new objects wait; None when there are none, since creating a collection is a Blender write.
    staging_collection: bpy.types.Collection | None
    next_display: Display  # the display once published, in the new plan's order
    created_objects_by_index: dict[int, bpy.types.Object]  # by new plan index: the new objects
    departing_objects: list[bpy.types.Object]  # the published objects the new display doesn't keep
    # By new plan index: kept objects that move onto rebuilt data or a new matrix.
    retained_object_updates_by_index: dict[int, ObjectResourceUpdate]
    renumbered_object_indices: list[int]  # new plan indices of kept objects whose index changed
    retired_resources: list[bpy.types.ID] = field(default_factory=list)  # what publication left unused


# A kept object's state before publication: its data, each slot's material, its element, and its transform if
# publication moves it.
Saved = tuple[bpy.types.Object, Any, list[bpy.types.Material | None], int, "Transform | None"]


@dataclass(frozen=True)
class Transform:
    """An object's own transform as Blender stores it, which restores exactly.

    Setting a matrix decomposes it again, which needn't give back the same components: a negative scale can
    return under another sign convention.
    """

    # Copies of Blender's values, typed Any: the bpy stubs type mathutils' Vector as a property descriptor.
    location: Any
    rotation_mode: str
    rotation: Any  # rotation_mode's own property: an Euler, a Quaternion, or the axis-angle values
    scale: Any

    @staticmethod
    def of(obj: bpy.types.Object) -> Transform:
        mode = obj.rotation_mode
        rotation = getattr(obj, _ROTATIONS.get(mode, "rotation_euler"))
        copied = rotation.copy() if hasattr(rotation, "copy") else tuple(rotation)
        return Transform(obj.location.copy(), mode, copied, obj.scale.copy())

    def restore(self, obj: bpy.types.Object) -> None:
        obj.rotation_mode = self.rotation_mode  # ty: ignore[invalid-assignment] - a mode read from an object
        obj.location = self.location
        setattr(obj, _ROTATIONS.get(self.rotation_mode, "rotation_euler"), self.rotation)
        obj.scale = self.scale


_ROTATIONS = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}  # else Euler


def unit_diff(plan: Plan, unit: DisplayRebuildSet) -> PlanDiff:
    """The diff that rebuilds `unit` of a display from the plan it shows: its objects, meshes, and materials.

    The objects that use a rebuilt mesh or material are changed and repointable.
    """
    records = plan.objects
    users = {
        index
        for index, record in enumerate(records)
        if record["mesh"] in unit.mesh_indices or any(m in unit.material_indices for m in record["material_slots"])
    }
    return {
        "previous_mesh_indices": [-1 if index in unit.mesh_indices else index for index in range(len(plan.meshes))],
        "previous_material_indices": [
            -1 if index in unit.material_indices else index for index in range(len(plan.materials))
        ],
        "previous_object_indices": list(range(len(records))),
        "changed_object_indices": sorted(unit.object_indices | users),
        "repointable_object_indices": sorted(users - unit.object_indices),
        "moved_object_indices": [],
        "removed_previous_object_indices": [],
    }


def sample_units(records: Sequence[ObjectRecord]) -> dict[str, DisplayRebuildSet]:
    """One unit of each kind the measurements and tests replace, from a plan's objects; a kind with none is left out.

    - object: the first object whose mesh other objects share;
    - mesh: the mesh with the most users;
    - material: the material in the most objects' slots;
    - asset: the floor with the most objects, with the meshes and materials only they use;
    - all: every object, mesh, and material.
    """
    users: dict[int, list[int]] = {}
    slotted: dict[int, int] = {}
    floors: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        mesh = record["mesh"]
        if mesh is not None:
            users.setdefault(mesh, []).append(index)
        for material in {m for m in record["material_slots"] if m is not None}:
            slotted[material] = slotted.get(material, 0) + 1
        floors.setdefault(record["floor"], []).append(index)
    units = {}
    shared = [objects for objects in users.values() if len(objects) > 1]
    if shared:
        units["object"] = DisplayRebuildSet(object_indices=frozenset({shared[0][0]}))
    if users:
        units["mesh"] = DisplayRebuildSet(mesh_indices=frozenset({max(users, key=lambda m: (len(users[m]), -m))}))
    if slotted:
        units["material"] = DisplayRebuildSet(
            material_indices=frozenset({max(slotted, key=lambda m: (slotted[m], -m))})
        )
    if floors:
        objects = set(max(floors.values(), key=len))
        others = [record for index, record in enumerate(records) if index not in objects]
        meshes = {records[i]["mesh"] for i in objects} - {r["mesh"] for r in others}
        slots = {m for i in objects for m in records[i]["material_slots"]}
        materials = slots - {m for r in others for m in r["material_slots"]}
        units["asset"] = DisplayRebuildSet(
            frozenset(objects),
            frozenset(m for m in meshes if m is not None),
            frozenset(m for m in materials if m is not None),
        )
    units["all"] = DisplayRebuildSet(frozenset(range(len(records))), frozenset(users), frozenset(slotted))
    return units


def prepare(
    plan: Plan, diff: PlanDiff, display: Display, users: DependentObjectUpdatePolicy, moves: bool = False
) -> PreparedDisplayUpdate:
    """Build what `plan` needs beyond what `diff` keeps of `display`, in a collection no scene links.

    With `moves`, the moved objects that kept_moves keeps are moved at publication rather than replaced.
    """
    meshes, materials = new_data(plan, diff, display.meshes, display.materials)
    moving = (
        kept_moves(plan, diff, diff["moved_object_indices"], display.objects.__getitem__, (meshes, materials), users)
        if moves
        else {}
    )
    kept = set(diff["repointable_object_indices"]) if users is DependentObjectUpdatePolicy.REPOINT else set()
    rebuilt = set(diff["changed_object_indices"]) - kept - set(moving)
    added = [index for index, old in enumerate(diff["previous_object_indices"]) if old == -1 or index in rebuilt]
    # Only the records the update builds from: reading the plan's whole list converts every record.
    needed = sorted({*added, *kept})
    records = dict(zip(needed, plan.objects_at(needed), strict=True))
    staging = bpy.data.collections.new("Prepared") if added else None
    objects: list[bpy.types.Object] = []
    created: dict[int, bpy.types.Object] = {}
    leaving = [display.objects[old] for old in diff["removed_previous_object_indices"]]
    renumbered = []
    for index, old in enumerate(diff["previous_object_indices"]):
        if old == -1 or index in rebuilt:
            assert staging is not None  # an added or rebuilt object, so there is a staging collection
            created[index] = new_object(index, records[index], meshes, materials, staging)
            objects.append(created[index])
            if old != -1:
                leaving.append(display.objects[old])
            continue
        objects.append(display.objects[old])
        if old != index:
            renumbered.append(index)
    repointed = {}
    for index in sorted(kept):
        record = records[index]
        mesh = record["mesh"]
        slots = [None if m is None else materials[m] for m in record["material_slots"]]
        repointed[index] = ObjectResourceUpdate(None if mesh is None else meshes[mesh], slots)
    repointed |= moving
    return PreparedDisplayUpdate(staging, Display(objects, meshes, materials), created, leaving, repointed, renumbered)


def kept_moves(  # noqa: PLR0913 - the plan, its diff, the candidates, the published objects, the data, the policy
    plan: Plan,
    diff: PlanDiff,
    moved: list[int],
    published: Callable[[int], bpy.types.Object],
    data: tuple[list[bpy.types.Mesh], list[bpy.types.Material]],
    users: DependentObjectUpdatePolicy,
) -> dict[int, ObjectResourceUpdate]:
    """By new plan index, the objects of `moved` (from the diff's) an update keeps, with new matrix, data, and slots.

    `published(old)` is the published object of old plan index `old`, and `data` the new plan's meshes and
    materials. A moved object is kept unless its old or new transform needs a shear parent, whose decomposition
    would change too, or, under replacement, its data changed. Only the moved objects' records are read.
    """
    meshes, materials = data
    kept = {}
    for index, record in zip(moved, plan.objects_at(moved), strict=True):
        obj = published(diff["previous_object_indices"][index])
        matrix = usd_matrix_to_blender(record["matrix"])
        if obj.parent is not None or sheared(matrix):
            continue
        mesh = record["mesh"]
        # A placeholder keeps its own bounds mesh: its bounds are the same, or it wouldn't have moved.
        moving = ObjectResourceUpdate(
            None if mesh is None else meshes[mesh],
            [None if m is None else materials[m] for m in record["material_slots"]],
            matrix,
        )
        same = (moving.mesh is None or moving.mesh == obj.data) and moving.material_slots == [
            slot.material for slot in obj.material_slots
        ]
        if same or users is DependentObjectUpdatePolicy.REPOINT:
            kept[index] = moving
    return kept


def new_data(
    plan: Plan, diff: PlanDiff, meshes: list[bpy.types.Mesh], materials: list[bpy.types.Material]
) -> tuple[list[bpy.types.Mesh], list[bpy.types.Material]]:
    """The new plan's meshes and materials: the published ones the diff matches, and new ones for the rest.

    Only the new ones' records are read, since reading a plan's whole list converts every record.
    """
    if (
        len(diff["previous_object_indices"]),
        len(diff["previous_mesh_indices"]),
        len(diff["previous_material_indices"]),
    ) != (
        plan.object_count,
        plan.mesh_count,
        plan.material_count,
    ):
        raise ValueError("The diff isn't the plan's")
    built = [index for index, old in enumerate(diff["previous_mesh_indices"]) if old == -1]
    mesh_records = dict(zip(built, plan.meshes_at(built), strict=True))
    material_records = plan.materials if -1 in diff["previous_material_indices"] else []
    return (
        [
            meshes[old] if old != -1 else new_mesh(mesh_records[index])
            for index, old in enumerate(diff["previous_mesh_indices"])
        ],
        [
            materials[old] if old != -1 else new_material(material_records[index])
            for index, old in enumerate(diff["previous_material_indices"])
        ],
    )


def publish(prepared: PreparedDisplayUpdate, display: Display, collection: bpy.types.Collection) -> Display:
    """Put the prepared update in place of `display` in `collection`; returns the published display."""
    new = prepared.next_display
    saved: list[Saved] = []
    try:
        for index in sorted(set(prepared.retained_object_updates_by_index) | set(prepared.renumbered_object_indices)):
            obj = new.objects[index]
            slots = [slot.material for slot in obj.material_slots]
            repoint = prepared.retained_object_updates_by_index.get(index)
            moving = repoint is not None and repoint.world_matrix is not None
            saved.append((obj, obj.data, slots, obj[ELEMENT], Transform.of(obj) if moving else None))
            if repoint is not None:
                if repoint.mesh is not None:
                    # The same slot count, and the slots link to the object, so each keeps its place.
                    obj.data = repoint.mesh
                for slot, material in zip(obj.material_slots, repoint.material_slots, strict=True):
                    slot.material = material
                if repoint.world_matrix is not None:
                    obj.matrix_world = repoint.world_matrix
            obj[ELEMENT] = index
        for obj in prepared.created_objects_by_index.values():
            for created in with_parent(obj):
                collection.objects.link(created)
                staging = prepared.staging_collection
                assert staging is not None
                staging.objects.unlink(created)
        for obj in prepared.departing_objects:
            for old in with_parent(obj):
                collection.objects.unlink(old)
    except BaseException:
        _restore(prepared, collection, saved)
        raise
    prepared.retired_resources = _retired(prepared, display)
    return new


def retire(prepared: PreparedDisplayUpdate) -> list[bpy.types.ID]:
    """Remove what publication left unused; returns the old meshes and materials kept for other users."""
    return retire_ids(prepared.retired_resources, prepared.staging_collection)


def retire_ids(retired: list[bpy.types.ID], staging_collection: bpy.types.Collection | None) -> list[bpy.types.ID]:
    """Remove the objects in `retired` and the staging collection, then the data in `retired` nothing uses."""
    objects = [i for i in retired if isinstance(i, bpy.types.Object)]
    staging = [] if staging_collection is None else [staging_collection]
    if objects or staging:
        bpy.data.batch_remove([*objects, *staging])
    # Only once the old objects are gone does a mesh or material count no users from the display.
    data = [i for i in retired if not isinstance(i, bpy.types.Object)]
    kept = [i for i in data if i.users > 0]
    unused = [i for i in data if i.users == 0]
    if unused:
        bpy.data.batch_remove(unused)
    return kept


def with_parent(obj: bpy.types.Object) -> list[bpy.types.Object]:
    """The object, then the shear parent empty that carries its transform, if any."""
    parent = obj.parent
    return [obj] if parent is None or SHEAR_PARENT not in parent else [obj, parent]


def _restore(prepared: PreparedDisplayUpdate, collection: bpy.types.Collection, saved: list[Saved]) -> None:
    """Put back what a failed publication changed; the prepared data stays for disposal."""
    for obj, data, slots, element, transform in reversed(saved):
        obj.data = data
        for slot, material in zip(obj.material_slots, slots, strict=True):
            slot.material = material
        obj[ELEMENT] = element
        if transform is not None:
            transform.restore(obj)
    for obj in prepared.created_objects_by_index.values():
        for created in with_parent(obj):
            if created.name in collection.objects:
                collection.objects.unlink(created)
            staging = prepared.staging_collection
            if staging is not None and created.name not in staging.objects:
                staging.objects.link(created)
    for obj in prepared.departing_objects:
        for old in with_parent(obj):
            if old.name not in collection.objects:
                collection.objects.link(old)


def _retired(prepared: PreparedDisplayUpdate, display: Display) -> list[bpy.types.ID]:
    """The old objects, with their shear parents and placeholder meshes, and the old meshes and materials."""
    retired: list[bpy.types.ID] = []
    planned = {mesh.as_pointer() for mesh in display.meshes}
    for old in prepared.departing_objects:
        retired.extend(with_parent(old))
        if old.data is not None and old.data.as_pointer() not in planned:  # a placeholder's own bounds
            retired.append(old.data)
    new = prepared.next_display
    meshes = {mesh.as_pointer() for mesh in new.meshes}
    materials = {material.as_pointer() for material in new.materials}
    retired.extend(mesh for mesh in display.meshes if mesh.as_pointer() not in meshes)
    retired.extend(material for material in display.materials if material.as_pointer() not in materials)
    return retired
