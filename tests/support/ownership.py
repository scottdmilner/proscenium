"""An oracle for the ownership index: every datablock's claims, read from the records now.

See lifecycle.md#ownership-and-lifecycle. The extension has one path to ownership, its runtime
index (proscenium.runtime). This one shares none of its code past reading the records, so a test
can compare the two: for every binding found in the scenes, in order, the first whose configuration
names a destination claims each datablock that destination's manifest names; then each tagged
collection no configuration names, as a copied destination is, claims for the binding its tag names.
A manifest that can't be read claims nothing and is listed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from proscenium.persistence import binding_records, manifests
from proscenium.persistence.records import Loaded, RefusedRecord
from proscenium.runtime import Claim

if TYPE_CHECKING:
    import bpy


def claims() -> tuple[dict[bpy.types.ID, list[Claim]], list[RefusedRecord]]:
    """Every datablock a manifest names, with its claims in the order found, and the manifests that can't be read."""
    found: dict[bpy.types.ID, list[Claim]] = {}
    unreadable: list[RefusedRecord] = []
    seen: set[bpy.types.Collection] = set()

    def claim(binding_id: str, destination: bpy.types.Collection) -> None:
        seen.add(destination)
        manifest = manifests.read_manifest(destination)
        if isinstance(manifest, RefusedRecord):
            unreadable.append(manifest)
        elif manifest is not None:
            for resource_id, entry in manifest.record.entries.items():
                if entry.datablock is not None:
                    found.setdefault(entry.datablock, []).append(Claim(binding_id, destination, resource_id))

    for _scene, binding_id, config in binding_records.config_records():
        destination = config.record.destination if isinstance(config, Loaded) else None
        if destination is not None and destination not in seen:  # a linked-copy scene's shared one is read once
            claim(binding_id, destination)
    for collection, tag in binding_records.tagged_collections():
        if isinstance(tag, Loaded) and collection not in seen:
            claim(tag.record.binding_id, collection)
    return found, unreadable
