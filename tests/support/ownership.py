"""An oracle for the ownership index: every datablock's claims, read from the records now.

See lifecycle.md#ownership-and-lifecycle. The extension has one path to ownership, its runtime
index (proscenium.binding.runtime). This one shares none of its code past reading the records, so a test
can compare the two: each local collection holding binding records, a copied destination's included, claims
each datablock its manifest names, for the first binding whose record it holds. A manifest that can't be read
claims nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from proscenium.binding.persistence import configs, manifests
from proscenium.binding.persistence.records import Loaded
from proscenium.binding.runtime import ownership
from proscenium.binding.runtime.ownership import Claim

if TYPE_CHECKING:
    from proscenium.binding.source_access.identifiers import BindingId


def claims() -> dict[bpy.types.ID, list[Claim]]:
    """Every datablock a manifest names, with its claims in the order found."""
    found: dict[bpy.types.ID, list[Claim]] = {}
    seen: set[bpy.types.Collection] = set()

    def claim(binding_id: BindingId, destination: bpy.types.Collection) -> None:
        seen.add(destination)
        manifest = manifests.read_manifest(destination)
        if isinstance(manifest, Loaded):
            for entry_key, entry in manifest.record.entries.items():
                if entry.datablock is not None:
                    found.setdefault(entry.datablock, []).append(Claim(binding_id, destination, entry_key))

    for collection, binding_id, _config in configs.read_configs():
        if collection not in seen:  # one holding two records claims once
            claim(binding_id, collection)
    return found


def assert_agrees() -> None:
    """Assert the ownership index's claims are the oracle's, as sets, for every datablock of every type."""
    expected = claims()
    for id_ in bpy.data.user_map().keys() | expected.keys():
        assert set(ownership.of(id_).claims) == set(expected.get(id_, [])), id_
