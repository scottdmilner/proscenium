"""Update a batched display to a new plan from its diff (M4, Phase D): update.py's counterpart for batch.py.

The new plan's groups (batch.groups) are matched to the published batches: each to the unclaimed batch of the
same destinations, object color, and primvar kinds that holds the most of its members' old counterparts.
Preparation builds, beside the display in a collection no scene links (TXN-05):
- each new mesh and material, as update.py does;
- a batch for each group no published batch matches;
- new points for a matched batch whose members, or a member's transform or primvars, changed. The members kept
  from the batch keep their selection state;
- each object the plan adds or changes, as update.py does, and each that was an instance before.

Publication then makes the change in one call (TXN-06), and undoes all of it if any step fails:
- it links the new objects and carriers in place of the old ones, and unlinks the removed ones;
- it moves a matched batch's carriers onto its new points, or else renumbers its points' elements in place;
- it moves a matched batch's prototype onto its group's mesh and materials, and the kept objects as update.py does.

A matched batch keeps its carriers and prototype under either user policy, which applies to the objects the
display keeps as objects: an instance has no identity outside its batch. Retirement removes the old objects and
batches, and the old data nothing uses once they are gone (OWN-08).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

import bpy
import numpy
from apply import new_object
from batch import Batch, BatchedDisplay, groups, new_batch, new_points, set_prototype
from batch_selection import states
from selection import ELEMENT
from update import Repoint, UserPolicy, new_data, retire_ids, with_parent

if TYPE_CHECKING:
    from collections.abc import Callable

    from plan_types import ObjectRecord, Plan, PlanDiff


@dataclass
class Rebatch:
    """A published batch the update keeps, and what publication changes on it."""

    batch: Batch  # once published
    record: ObjectRecord  # a member's, whose mesh and materials the prototype shows
    reprototyped: bool  # whether the prototype moves onto another mesh or materials
    points: bpy.types.Mesh | None  # new points the carriers move onto, or None to keep theirs
    previous: bpy.types.Mesh  # the points the carriers are on before publication
    renumbered: bool  # whether the kept points' elements change in place


@dataclass
class Prepared:
    """An update built beside the published batched display, which it doesn't touch until publication."""

    # Where the new objects and carriers wait; None when there are none, since creating a collection is a write.
    staging: bpy.types.Collection | None
    display: BatchedDisplay  # the display once published
    created: dict[int, bpy.types.Object]  # by new plan index: the new objects
    added: list[Batch]  # the new batches
    kept: list[Rebatch]
    dropped: list[Batch]  # the published batches no group matched
    leaving: list[bpy.types.Object]  # the published objects the new display doesn't keep
    repointed: dict[int, Repoint]  # by new plan index: kept objects that move onto rebuilt data
    renumbered: list[int]  # new plan indices of kept objects whose index changed
    retired: list[bpy.types.ID] = field(default_factory=list)  # what publication left unused


def prepare(plan: Plan, diff: PlanDiff, display: BatchedDisplay, users: UserPolicy) -> Prepared:
    """Build what `plan` needs beyond what `diff` keeps of `display`, in a collection no scene links."""
    records = plan.objects  # each read of a plan's list converts all its records, so each is read once
    meshes, materials = new_data(plan, records, diff, display.meshes, display.materials)
    previous = diff["objects"]
    repointable = set(diff["repointable"])
    # Members whose points change; a change to only the mesh or materials is the prototype's.
    moved = set(diff["changed"]) - repointable
    rebuilt = set(diff["changed"]) - (repointable if users is UserPolicy.REPOINT else set())
    shared, single = groups(records)
    matched = _matches(shared, previous, display.batches)
    made = [index for index in single if index not in _kept_objects(single, previous, display, rebuilt)]
    staging = bpy.data.collections.new("Prepared") if made or None in matched else None
    serial = display.serial
    batches, added, kept = [], [], []
    for (key, members), old in zip(shared.items(), matched, strict=True):
        if old is None:
            assert staging is not None  # a group no batch matches, so there is a staging collection
            batch = new_batch(serial, key, members, records, meshes, materials, staging, display.nodes)
            serial += 1
            added.append(batch)
            batches.append(batch)
            continue
        olds = [previous[index] for index in members]
        points = None
        if olds != old.elements or moved.intersection(members):
            # The members kept from this batch keep their state, so an update keeps their selection.
            position = {element: point for point, element in enumerate(old.elements)}
            held = states(old)
            carried = [
                int(held[position[o]]) if o in position and index not in moved else 0
                for index, o in zip(members, olds, strict=True)
            ]
            points = new_points(serial, members, records, carried)
            serial += 1
        record = records[members[0]]
        mesh = record["mesh"]
        assert mesh is not None  # batch_key left out placeholders
        slots = [None if m is None else materials[m] for m in record["material_slots"]]
        reprototyped = (
            old.prototype.data != meshes[mesh] or [slot.material for slot in old.prototype.material_slots] != slots
        )
        batch = Batch(old.carriers, old.prototype, members, key)
        kept.append(Rebatch(batch, record, reprototyped, points, old.points, points is None and olds != members))
        batches.append(batch)
    claimed = {old.prototype.as_pointer() for old in matched if old is not None}
    dropped = [old for old in display.batches if old.prototype.as_pointer() not in claimed]

    objects: dict[int, bpy.types.Object] = {}
    created: dict[int, bpy.types.Object] = {}
    renumbered, repointed = [], {}
    for index in single:
        if index not in made:
            objects[index] = display.objects[previous[index]]
            if previous[index] != index:
                renumbered.append(index)
            if index in repointable:
                record = records[index]
                mesh = record["mesh"]
                slots = [None if m is None else materials[m] for m in record["material_slots"]]
                repointed[index] = Repoint(None if mesh is None else meshes[mesh], slots)
            continue
        assert staging is not None  # an added or rebuilt object, so there is a staging collection
        objects[index] = created[index] = new_object(index, records[index], meshes, materials, staging)
    kept_pointers = {obj.as_pointer() for obj in objects.values()}
    leaving = [obj for obj in display.objects.values() if obj.as_pointer() not in kept_pointers]
    new = BatchedDisplay(objects, batches, meshes, materials, display.nodes, serial)
    return Prepared(staging, new, created, added, kept, dropped, leaving, repointed, renumbered)


def publish(prepared: Prepared, display: BatchedDisplay, collection: bpy.types.Collection) -> BatchedDisplay:
    """Put the prepared update in place of `display` in `collection`; returns the published display."""
    new = prepared.display
    undo: list[Callable[[], None]] = []  # each change's reversal, in the order made
    try:
        for index, repoint in prepared.repointed.items():
            obj = new.objects[index]
            undo.append(_saved(obj))
            if repoint.data is not None:
                # The same slot count, and the slots link to the object, so each keeps its place.
                obj.data = repoint.data
            for slot, material in zip(obj.material_slots, repoint.materials, strict=True):
                slot.material = material
        for index in prepared.renumbered:
            obj = new.objects[index]
            undo.append(partial(obj.__setitem__, ELEMENT, obj[ELEMENT]))
            obj[ELEMENT] = index
        for rebatch in prepared.kept:
            batch = rebatch.batch
            if rebatch.reprototyped:
                undo.append(_saved(batch.prototype))
                set_prototype(batch.prototype, rebatch.record, new.meshes, new.materials)
            if rebatch.points is not None:
                for carrier in batch.carriers:
                    undo.append(partial(setattr, carrier, "data", carrier.data))
                    carrier.data = rebatch.points
            elif rebatch.renumbered:
                elements = _data(rebatch.previous.attributes[ELEMENT])
                held = numpy.empty(len(batch.elements), dtype=numpy.int32)
                elements.foreach_get("value", held)
                undo.append(partial(elements.foreach_set, "value", held))
                elements.foreach_set("value", numpy.array(batch.elements, dtype=numpy.int32))
        staging = prepared.staging
        arriving = [o for obj in prepared.created.values() for o in with_parent(obj)]
        arriving += [carrier for batch in prepared.added for carrier in batch.carriers]
        for obj in arriving:
            assert staging is not None
            collection.objects.link(obj)
            undo.append(partial(collection.objects.unlink, obj))
            staging.objects.unlink(obj)
            undo.append(partial(staging.objects.link, obj))
        departing = [o for obj in prepared.leaving for o in with_parent(obj)]
        departing += [carrier for batch in prepared.dropped for carrier in batch.carriers]
        for obj in departing:
            collection.objects.unlink(obj)
            undo.append(partial(collection.objects.link, obj))
    except BaseException:
        for reverse in reversed(undo):
            reverse()
        raise
    prepared.retired = _retired(prepared, display)
    return new


def retire(prepared: Prepared) -> list[bpy.types.ID]:
    """Remove what publication left unused; returns the old meshes and materials kept for other users."""
    return retire_ids(prepared.retired, prepared.staging)


def _matches(shared: dict[tuple[Any, ...], list[int]], previous: list[int], batches: list[Batch]) -> list[Batch | None]:
    """For each group, in order, the published batch that keeps showing it, or None for a new batch."""
    holding = {element: number for number, batch in enumerate(batches) for element in batch.elements}
    claimed: set[int] = set()
    matched = []
    for key, members in shared.items():
        # Everything in a key but the mesh, the slots, and the repeat: what a batch's carriers and prototype show
        # besides its mesh and materials, and the kinds of its points' primvars.
        looks = key[2:-1]
        counts = Counter(
            holding[old]
            for old in (previous[index] for index in members)
            if old in holding and batches[holding[old]].key[2:-1] == looks
        )
        best = max((n for n in counts if n not in claimed), key=lambda n: (counts[n], -n), default=None)
        if best is not None:
            claimed.add(best)
        matched.append(None if best is None else batches[best])
    return matched


def _kept_objects(single: list[int], previous: list[int], display: BatchedDisplay, rebuilt: set[int]) -> set[int]:
    """The new plan indices of the published objects that stay objects, unrebuilt."""
    return {index for index in single if previous[index] in display.objects and index not in rebuilt}


def _saved(obj: bpy.types.Object) -> Callable[[], None]:
    """What puts back an object's data and each slot's material."""
    data, slots = obj.data, [slot.material for slot in obj.material_slots]

    def restore() -> None:
        obj.data = data
        for slot, material in zip(obj.material_slots, slots, strict=True):
            slot.material = material

    return restore


def _retired(prepared: Prepared, display: BatchedDisplay) -> list[bpy.types.ID]:
    """The old objects and batches, with their shear parents, placeholder meshes, and points, and the old data."""
    retired: list[bpy.types.ID] = []
    planned = {mesh.as_pointer() for mesh in display.meshes}
    for old in prepared.leaving:
        retired.extend(with_parent(old))
        if old.data is not None and old.data.as_pointer() not in planned:  # a placeholder's own bounds
            retired.append(old.data)
    for batch in prepared.dropped:
        retired.extend([*batch.carriers, batch.prototype, batch.points])
    retired.extend(rebatch.previous for rebatch in prepared.kept if rebatch.points is not None)
    new = prepared.display
    meshes = {mesh.as_pointer() for mesh in new.meshes}
    materials = {material.as_pointer() for material in new.materials}
    retired.extend(mesh for mesh in display.meshes if mesh.as_pointer() not in meshes)
    retired.extend(material for material in display.materials if material.as_pointer() not in materials)
    return retired


def _data(attribute: bpy.types.Attribute) -> Any:
    return attribute.data  # ty: ignore[unresolved-attribute] - Attribute.data is missing from the stubs
