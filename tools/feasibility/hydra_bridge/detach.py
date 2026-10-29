"""Detach an applied display (M4, B7): Detach As-Is in the object baseline.

Detach releases what survives in the destination collection when it runs, Blender-side edits and deletions
included, and reads no USD. The baseline ties Blender data to its binding only through ID properties
(apply.OBJECT_PROPERTIES and MATERIAL_PROPERTIES), so those are what detach removes. It has no handlers,
drivers, modifiers, node groups, or overlays, and its correspondence and selection associations live in the
bridge's Interaction, not in Blender data.

Everything else is ordinary Blender data and stays:
- meshes, shared where they were;
- objects, with their transforms, visibility per destination, object color, and constant primvars as ID
  properties, which an Attribute node reads;
- shear parent empties, by ordinary parenting;
- placeholders, as bounds boxes and empties;
- materials, in object-linked slots;
- collection links and the selection.
So detaching changes no appearance, and there is nothing to report under DET-04.

A batched display (batch.py, M4 Phase D) ties its instances to the binding only through the
`proscenium_element` attribute on each batch's points mesh, which names each instance's element, and which
detach removes. Everything else in a batch is ordinary Blender data that works without the binding, so it
stays: the carriers, their Geometry Nodes modifiers and node group, the prototypes they instance, and the
points' transforms, selection states, and primvars, which the node group and Attribute nodes read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from apply import MATERIAL_PROPERTIES, OBJECT_PROPERTIES
from batch import prototype_of
from selection import ELEMENT

if TYPE_CHECKING:
    import bpy


@dataclass(frozen=True)
class Detached:
    """What detach released."""

    objects: int
    materials: int
    properties: int  # ID properties removed
    carriers: int
    attributes: int  # point attributes removed


def detach(collection: bpy.types.Collection) -> Detached:
    """Release the display in `collection` as ordinary Blender data."""
    objects = [obj for obj in collection.all_objects if any(key in obj for key in OBJECT_PROPERTIES)]
    # A carrier is an object whose mesh's points name their elements.
    carriers = [obj for obj in collection.all_objects if obj.type == "MESH" and ELEMENT in _mesh(obj).attributes]
    prototypes = [p for p in map(prototype_of, carriers) if p is not None]
    materials = {
        slot.material.as_pointer(): slot.material
        for obj in [*objects, *prototypes]
        for slot in obj.material_slots
        if slot.material is not None and any(key in slot.material for key in MATERIAL_PROPERTIES)
    }
    removed = 0
    for ids, keys in ((objects, OBJECT_PROPERTIES), (list(materials.values()), MATERIAL_PROPERTIES)):
        for released in ids:
            for key in keys:
                if key in released:
                    del released[key]
                    removed += 1
    points = {_mesh(carrier).as_pointer(): _mesh(carrier) for carrier in carriers}
    for mesh in points.values():
        mesh.attributes.remove(mesh.attributes[ELEMENT])
    return Detached(len(objects), len(materials), removed, len(carriers), len(points))


def _mesh(obj: bpy.types.Object) -> Any:
    """A mesh object's mesh; Object.data is typed as every kind of object data."""
    return obj.data
