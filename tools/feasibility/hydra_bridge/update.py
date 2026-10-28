"""Update an applied display to a new plan from its diff (M4, B6 and C2): what an update costs in the object baseline.

The diff (diff_plans) says which of the published display's meshes, materials, and objects the new plan keeps.
Preparation builds the rest beside the display, in a collection no scene links, so it changes nothing the
display uses (TXN-05):
- each new mesh and material;
- each added object, and each changed one. Under repointing, a changed object that differs only in its mesh or
  materials is kept instead.

Publication then makes the change in one call (TXN-06):
- it links the new objects in place of the old ones, and unlinks the removed ones;
- it moves the kept users of a rebuilt mesh or material onto it;
- it renumbers the kept objects whose plan index changed.

It undoes all of that if any step fails. Retirement removes the old objects, and the old meshes and materials
nothing uses once those are gone. One that something outside the display still uses is left intact (OWN-08).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import bpy
from apply import SHEAR_PARENT, Display, new_material, new_mesh, new_object
from selection import ELEMENT

if TYPE_CHECKING:
    from collections.abc import Sequence

    from plan_types import ObjectRecord, Plan, PlanDiff


class UserPolicy(StrEnum):
    """What happens to the objects that differ only in using a rebuilt mesh or material."""

    REPOINT = "repoint"  # they are kept, and publication moves them onto the rebuilt data
    REPLACE = "replace"  # they are replaced


@dataclass(frozen=True)
class Unit:
    """Part of a display to rebuild from an unchanged plan, by plan index (unit_diff)."""

    objects: frozenset[int] = frozenset()
    meshes: frozenset[int] = frozenset()
    materials: frozenset[int] = frozenset()


@dataclass
class Repoint:
    """A kept object's data and slots, as publication sets them."""

    data: Any  # the object's new mesh; Object.data is typed as every kind of object data
    materials: list[bpy.types.Material | None]


@dataclass
class Prepared:
    """An update built beside the published display, which it doesn't touch until publication."""

    staging: bpy.types.Collection
    display: Display  # the display once published, in the new plan's order
    created: dict[int, bpy.types.Object]  # by new plan index: the new objects
    leaving: list[bpy.types.Object]  # the published objects the new display doesn't keep
    repointed: dict[int, Repoint]  # by new plan index: kept objects that move onto rebuilt data
    renumbered: list[int]  # new plan indices of kept objects whose index changed
    retired: list[bpy.types.ID] = field(default_factory=list)  # what publication left unused


# A kept object's state before publication: its data, each slot's material, and its element.
Saved = tuple[bpy.types.Object, Any, list[bpy.types.Material | None], int]


def unit_diff(plan: Plan, unit: Unit) -> PlanDiff:
    """The diff that rebuilds `unit` of a display from the plan it shows: its objects, meshes, and materials.

    The objects that use a rebuilt mesh or material are changed and repointable.
    """
    records = plan.objects
    users = {
        index
        for index, record in enumerate(records)
        if record["mesh"] in unit.meshes or any(m in unit.materials for m in record["material_slots"])
    }
    return {
        "meshes": [-1 if index in unit.meshes else index for index in range(len(plan.meshes))],
        "materials": [-1 if index in unit.materials else index for index in range(len(plan.materials))],
        "objects": list(range(len(records))),
        "changed": sorted(unit.objects | users),
        "repointable": sorted(users - unit.objects),
        "removed": [],
    }


def sample_units(records: Sequence[ObjectRecord]) -> dict[str, Unit]:
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
        units["object"] = Unit(objects=frozenset({shared[0][0]}))
    if users:
        units["mesh"] = Unit(meshes=frozenset({max(users, key=lambda m: (len(users[m]), -m))}))
    if slotted:
        units["material"] = Unit(materials=frozenset({max(slotted, key=lambda m: (slotted[m], -m))}))
    if floors:
        objects = set(max(floors.values(), key=len))
        others = [record for index, record in enumerate(records) if index not in objects]
        meshes = {records[i]["mesh"] for i in objects} - {r["mesh"] for r in others}
        slots = {m for i in objects for m in records[i]["material_slots"]}
        materials = slots - {m for r in others for m in r["material_slots"]}
        units["asset"] = Unit(
            frozenset(objects),
            frozenset(m for m in meshes if m is not None),
            frozenset(m for m in materials if m is not None),
        )
    units["all"] = Unit(frozenset(range(len(records))), frozenset(users), frozenset(slotted))
    return units


def prepare(plan: Plan, diff: PlanDiff, display: Display, users: UserPolicy) -> Prepared:
    """Build what `plan` needs beyond what `diff` keeps of `display`, in a collection no scene links."""
    # Each read of a plan's list converts all its records, so each is read once.
    records, mesh_records, material_records = plan.objects, plan.meshes, plan.materials
    if (len(diff["objects"]), len(diff["meshes"]), len(diff["materials"])) != (
        len(records),
        len(mesh_records),
        len(material_records),
    ):
        raise ValueError("The diff isn't the plan's")
    meshes = [
        display.meshes[old] if old != -1 else new_mesh(mesh_records[index]) for index, old in enumerate(diff["meshes"])
    ]
    materials = [
        display.materials[old] if old != -1 else new_material(material_records[index])
        for index, old in enumerate(diff["materials"])
    ]
    kept = set(diff["repointable"]) if users is UserPolicy.REPOINT else set()
    rebuilt = set(diff["changed"]) - kept
    staging = bpy.data.collections.new("Prepared")
    objects: list[bpy.types.Object] = []
    created: dict[int, bpy.types.Object] = {}
    leaving = [display.objects[old] for old in diff["removed"]]
    renumbered = []
    for index, old in enumerate(diff["objects"]):
        if old == -1 or index in rebuilt:
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
        repointed[index] = Repoint(None if mesh is None else meshes[mesh], slots)
    return Prepared(staging, Display(objects, meshes, materials), created, leaving, repointed, renumbered)


def publish(prepared: Prepared, display: Display, collection: bpy.types.Collection) -> Display:
    """Put the prepared update in place of `display` in `collection`; returns the published display."""
    new = prepared.display
    saved: list[Saved] = []
    try:
        for index in sorted(set(prepared.repointed) | set(prepared.renumbered)):
            obj = new.objects[index]
            saved.append((obj, obj.data, [slot.material for slot in obj.material_slots], obj[ELEMENT]))
            repoint = prepared.repointed.get(index)
            if repoint is not None:
                if repoint.data is not None:
                    # The same slot count, and the slots link to the object, so each keeps its place.
                    obj.data = repoint.data
                for slot, material in zip(obj.material_slots, repoint.materials, strict=True):
                    slot.material = material
            obj[ELEMENT] = index
        for obj in prepared.created.values():
            for created in _with_parent(obj):
                collection.objects.link(created)
                prepared.staging.objects.unlink(created)
        for obj in prepared.leaving:
            for old in _with_parent(obj):
                collection.objects.unlink(old)
    except BaseException:
        _restore(prepared, collection, saved)
        raise
    prepared.retired = _retired(prepared, display)
    return new


def retire(prepared: Prepared) -> list[bpy.types.ID]:
    """Remove what publication left unused; returns the old meshes and materials kept for other users."""
    objects = [i for i in prepared.retired if isinstance(i, bpy.types.Object)]
    bpy.data.batch_remove([*objects, prepared.staging])
    # Only once the old objects are gone does a mesh or material count no users from the display.
    data = [i for i in prepared.retired if not isinstance(i, bpy.types.Object)]
    kept = [i for i in data if i.users > 0]
    bpy.data.batch_remove([i for i in data if i.users == 0])
    return kept


def _with_parent(obj: bpy.types.Object) -> list[bpy.types.Object]:
    """The object, then the shear parent empty that carries its transform, if any."""
    parent = obj.parent
    return [obj] if parent is None or SHEAR_PARENT not in parent else [obj, parent]


def _restore(prepared: Prepared, collection: bpy.types.Collection, saved: list[Saved]) -> None:
    """Put back what a failed publication changed; the prepared data stays for disposal."""
    for obj, data, slots, element in reversed(saved):
        obj.data = data
        for slot, material in zip(obj.material_slots, slots, strict=True):
            slot.material = material
        obj[ELEMENT] = element
    for obj in prepared.created.values():
        for created in _with_parent(obj):
            if created.name in collection.objects:
                collection.objects.unlink(created)
            if created.name not in prepared.staging.objects:
                prepared.staging.objects.link(created)
    for obj in prepared.leaving:
        for old in _with_parent(obj):
            if old.name not in collection.objects:
                collection.objects.link(old)


def _retired(prepared: Prepared, display: Display) -> list[bpy.types.ID]:
    """The old objects, with their shear parents and placeholder meshes, and the old meshes and materials."""
    retired: list[bpy.types.ID] = []
    planned = {mesh.as_pointer() for mesh in display.meshes}
    for old in prepared.leaving:
        retired.extend(_with_parent(old))
        if old.data is not None and old.data.as_pointer() not in planned:  # a placeholder's own bounds
            retired.append(old.data)
    new = prepared.display
    meshes = {mesh.as_pointer() for mesh in new.meshes}
    materials = {material.as_pointer() for material in new.materials}
    retired.extend(mesh for mesh in display.meshes if mesh.as_pointer() not in meshes)
    retired.extend(material for material in display.materials if material.as_pointer() not in materials)
    return retired
