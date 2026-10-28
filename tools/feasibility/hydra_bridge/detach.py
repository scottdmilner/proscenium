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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from apply import MATERIAL_PROPERTIES, OBJECT_PROPERTIES

if TYPE_CHECKING:
    import bpy


@dataclass(frozen=True)
class Detached:
    """What detach released."""

    objects: int
    materials: int
    properties: int  # ID properties removed


def detach(collection: bpy.types.Collection) -> Detached:
    """Release the display in `collection` as ordinary Blender data."""
    objects = [obj for obj in collection.all_objects if any(key in obj for key in OBJECT_PROPERTIES)]
    materials = {
        slot.material.as_pointer(): slot.material
        for obj in objects
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
    return Detached(len(objects), len(materials), removed)
