"""Replace part of an applied plan's display (M4, B6): what a small update costs in the object baseline.

Preparation builds the new data beside the published display, in a collection no scene links, so it changes
nothing the display uses (TXN-05). Publication then links the new objects in place of the old ones in one call
(TXN-06). Under repointing it also moves the kept users of a replaced mesh or material onto the replacement, and
undoes all of it if any step fails. Retirement removes the old objects, and the old meshes and materials nothing
else uses. One that something outside the display still uses is left intact (OWN-08).

Change discovery is out of scope: the caller names the unit, and `plan` keeps the display's objects, meshes, and
materials in the same order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

import bpy
from apply import SHEAR_PARENT, Display, new_material, new_mesh, new_object

if TYPE_CHECKING:
    from collections.abc import Sequence

    from plan_types import ObjectRecord, Plan


class UserPolicy(StrEnum):
    """What happens to the objects that use a replaced mesh or material, when the unit doesn't name them."""

    REPOINT = "repoint"  # they are kept, and publication moves them onto the replacement
    REPLACE = "replace"  # they are replaced too


@dataclass(frozen=True)
class Unit:
    """What a replacement rebuilds, by plan index."""

    objects: frozenset[int] = frozenset()
    meshes: frozenset[int] = frozenset()
    materials: frozenset[int] = frozenset()


@dataclass
class Prepared:
    """A replacement built beside the published display, which it doesn't touch until publication."""

    staging: bpy.types.Collection
    display: Display  # the display once published: replacements in place of what they replace
    objects: dict[int, bpy.types.Object]  # by plan index: the new objects
    repointed: dict[int, int | None]  # by plan index, the kept objects to move onto a replacement: their plan mesh
    materials: dict[int, bpy.types.Material]  # by the pointer of each replaced material: its replacement
    retired: list[bpy.types.ID] = field(default_factory=list)  # what publication left unused


# A repointed object's plan index and each slot's material before publication.
Saved = tuple[int, list[bpy.types.Material | None]]


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


def prepare(plan: Plan, display: Display, unit: Unit, users: UserPolicy) -> Prepared:
    """Build `unit`'s replacements from `plan`, and the new objects, in a collection no scene links."""
    # Each read of a plan's list converts all its records, so each is read once.
    records, mesh_records, material_records = plan.objects, plan.meshes, plan.materials
    sizes = (len(records), len(mesh_records), len(material_records))
    if sizes != (len(display.objects), len(display.meshes), len(display.materials)) or any(
        record["source"] != obj["proscenium_source"] for record, obj in zip(records, display.objects, strict=True)
    ):
        raise ValueError("The plan doesn't keep the display's objects, meshes, and materials in order")
    materials = list(display.materials)
    for index in unit.materials:
        materials[index] = new_material(material_records[index])
    meshes = list(display.meshes)
    for index in unit.meshes:
        meshes[index] = new_mesh(mesh_records[index])
    using = {
        index
        for index, record in enumerate(records)
        if record["mesh"] in unit.meshes or any(m in unit.materials for m in record["material_slots"])
    }
    replaced = unit.objects | using if users is UserPolicy.REPLACE else unit.objects
    staging = bpy.data.collections.new("Prepared")
    created = {index: new_object(index, records[index], meshes, materials, staging) for index in sorted(replaced)}
    objects = [created.get(index, obj) for index, obj in enumerate(display.objects)]
    return Prepared(
        staging,
        Display(objects, meshes, materials),
        created,
        {index: records[index]["mesh"] for index in sorted(using - replaced)},
        {display.materials[index].as_pointer(): materials[index] for index in unit.materials},
    )


def publish(prepared: Prepared, display: Display, collection: bpy.types.Collection) -> Display:
    """Put the prepared objects in place of `display`'s, in `collection`; returns the published display."""
    new = prepared.display
    saved: list[Saved] = []
    try:
        for index, mesh in prepared.repointed.items():
            obj = display.objects[index]
            slots = [slot.material for slot in obj.material_slots]
            saved.append((index, slots))
            if mesh is not None:
                # The same slot count, and the slots link to the object, so each keeps its material.
                obj.data = new.meshes[mesh]
            for slot, material in zip(obj.material_slots, slots, strict=True):
                if material is not None:
                    slot.material = prepared.materials.get(material.as_pointer(), material)
        for index, obj in prepared.objects.items():
            for created in _with_parent(obj):
                collection.objects.link(created)
                prepared.staging.objects.unlink(created)
            for old in _with_parent(display.objects[index]):
                collection.objects.unlink(old)
    except BaseException:
        _restore(prepared, display, collection, saved)
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


def _restore(prepared: Prepared, display: Display, collection: bpy.types.Collection, saved: list[Saved]) -> None:
    """Put back what a failed publication changed; the prepared data stays for disposal."""
    for index, slots in reversed(saved):
        obj, mesh = display.objects[index], prepared.repointed[index]
        if mesh is not None:
            obj.data = display.meshes[mesh]
        for slot, material in zip(obj.material_slots, slots, strict=True):
            slot.material = material
    for index, obj in prepared.objects.items():
        for created in _with_parent(obj):
            if created.name in collection.objects:
                collection.objects.unlink(created)
            if created.name not in prepared.staging.objects:
                prepared.staging.objects.link(created)
        for old in _with_parent(display.objects[index]):
            if old.name not in collection.objects:
                collection.objects.link(old)


def _retired(prepared: Prepared, display: Display) -> list[bpy.types.ID]:
    """The old objects, with their shear parents and placeholder meshes, and the old meshes and materials."""
    retired: list[bpy.types.ID] = []
    planned = {mesh.as_pointer() for mesh in display.meshes}
    for index in prepared.objects:
        old = display.objects[index]
        retired.extend(_with_parent(old))
        if old.data is not None and old.data.as_pointer() not in planned:  # a placeholder's own bounds
            retired.append(old.data)
    new = prepared.display
    retired.extend(old for old, kept in zip(display.meshes, new.meshes, strict=True) if old != kept)
    retired.extend(old for old, kept in zip(display.materials, new.materials, strict=True) if old != kept)
    return retired
