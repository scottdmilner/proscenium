"""An oracle for the ownership index: every datablock's claims, read from the records now.

See lifecycle.md#ownership-and-lifecycle. The extension has one path to ownership, its runtime
index (proscenium.runtime). This one shares none of its code past reading the records, so a test
can compare the two: for every binding found in the scenes, in order, the first whose configuration
names a destination claims each datablock that destination's manifest names; then each tagged
collection no configuration names, as a copied destination is, claims for the binding its tag names.
A manifest that can't be read claims nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from proscenium import runtime
from proscenium.persistence import binding_records, manifests
from proscenium.persistence.records import Loaded
from proscenium.runtime import Claim

if TYPE_CHECKING:
    from proscenium.core.binding_ids import BindingId


def claims() -> dict[bpy.types.ID, list[Claim]]:
    """Every datablock a manifest names, with its claims in the order found."""
    found: dict[bpy.types.ID, list[Claim]] = {}
    seen: set[bpy.types.Collection] = set()

    def claim(binding_id: BindingId, destination: bpy.types.Collection) -> None:
        seen.add(destination)
        manifest = manifests.read_manifest(destination)
        if isinstance(manifest, Loaded):
            for resource_id, entry in manifest.record.entries.items():
                if entry.datablock is not None:
                    found.setdefault(entry.datablock, []).append(Claim(binding_id, destination, resource_id))

    for _scene, binding_id, config in binding_records.read_configs():
        destination = config.record.destination if isinstance(config, Loaded) else None
        if destination is not None and destination not in seen:  # a linked-copy scene's shared one is read once
            claim(binding_id, destination)
    for collection, tag in binding_records.read_tags():
        if isinstance(tag, Loaded) and collection not in seen:
            claim(tag.record.binding_id, collection)
    return found


def assert_agrees() -> None:
    """Assert the ownership index's claims are the oracle's, as sets, for every datablock of every type."""
    expected = claims()
    for id_ in bpy.data.user_map().keys() | expected.keys():
        assert set(runtime.ownership(id_).claims) == set(expected.get(id_, [])), id_
