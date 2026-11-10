"""M5 Phase S: lookups on the bindings' records, read when called, with the baseline's display as a manifest.

The child applies the display into a binding's destination, and this writes its manifest as ownership_timing.py does.
It then times, each REPEATS times, with the datablocks looked up before the clock starts:

- ownership of one object, and of 1,000 at once as a box select asks, from their users (bpy.data.user_map): the
  collections holding binding records among their users (a manifest's pointer is a user), and those manifests;
  ownership.of for one, and a scan of the stored entries for the pointers for 1,000;
- ownership by scan, for comparison: every binding record and every manifest read, then the claims;
- a binding lookup, binding_configs.find_binding;
- reading the binding's manifest whole, as a synchronization does.

M5 Phase S first measured these against M3's cache of the records, which it then removed (runtime-record.md). Each
way is checked against ownership.of. user_map scans the whole file, so its cost grows with every datablock in it, not
only the managed ones.
"""

from __future__ import annotations

import statistics
import time
from typing import TYPE_CHECKING, Any

import bpy
import ownership_timing

if TYPE_CHECKING:
    from collections.abc import Callable

REPEATS = 10
BOX = 1000  # the objects a box select asks about at once


def _stats(call: Callable[[], Any]) -> dict[str, Any]:
    values = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        call()
        values.append(time.perf_counter() - start)
    return {
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "repeats": len(values),
        "values": values,
    }


def _claims_by_scan(target: bpy.types.ID) -> list[tuple[str, str]]:
    """No cache: every binding record and every manifest read, then the claims on target."""
    from proscenium.binding.persistence import configs, manifests, records

    found = []
    seen = set()
    for collection, binding_id, _config in configs.read_configs():
        if collection in seen:
            continue
        seen.add(collection)
        manifest = manifests.read_manifest(collection)
        if isinstance(manifest, records.LoadedRecord):
            found += [(binding_id, k) for k, e in manifest.record.entries.items() if e.datablock == target]
    return found


def _claims_by_users(targets: list[bpy.types.ID]) -> dict[int, list[tuple[str, str]]]:
    """No cache: the targets' users, the binding collections among them, and a scan of each one's stored entries."""
    from proscenium.binding.persistence import configs, manifests, records

    user_map = bpy.data.user_map(subset=targets)
    holders: dict[bpy.types.Collection, set[int]] = {}
    for target in targets:
        for user in user_map[target]:
            if isinstance(user, bpy.types.Collection) and configs.binding_ids(user):
                holders.setdefault(user, set()).add(target.session_uid)
    found: dict[int, list[tuple[str, str]]] = {t.session_uid: [] for t in targets}
    for collection, wanted in holders.items():
        binding_id = configs.binding_ids(collection)[0]
        for entry_key, entry in collection[records.NAMESPACE][manifests.MANIFEST_KEY]["entries"].items():
            datablock = entry.get("datablock")
            if datablock is not None and datablock.session_uid in wanted:
                found[datablock.session_uid].append((binding_id, entry_key))
    return found


def measure(binding_id: Any, display: Any, records: list[dict[str, Any]], materials: list[dict[str, Any]]) -> dict:
    """Write the manifest, then time the lookups."""
    from proscenium.binding.persistence import manifests
    from proscenium.binding.persistence.manifests import Manifest
    from proscenium.binding.runtime import binding_configs, ownership

    manifest = Manifest(ownership_timing.entries(display, records, materials))
    ownership.set_manifest(binding_id, manifest)
    found = binding_configs.find_binding(binding_id)
    assert found is not None and found.destination is not None
    destination = found.destination
    objects = list(display.objects)
    target = objects[len(objects) // 2]
    box = objects[:BOX]
    # Each way without the cache gives the cache's answer.
    expected = [(c.binding_id, c.entry_key) for c in ownership.of(target).claims]
    assert len(expected) == 1
    assert _claims_by_scan(target) == expected
    assert _claims_by_users([target])[target.session_uid] == expected
    by_users = _claims_by_users(box)
    assert all(by_users[o.session_uid] == [(c.binding_id, c.entry_key) for c in ownership.of(o).claims] for o in box)
    timings = {
        "single: ownership.of": _stats(lambda: ownership.of(target)),
        f"ownership by users, {len(box):,} at once": _stats(lambda: _claims_by_users(box)),
        "single: ownership by scan": _stats(lambda: _claims_by_scan(target)),
        "single: find_binding": _stats(lambda: binding_configs.find_binding(binding_id)),
        "the manifest read whole": _stats(lambda: manifests.read_manifest(destination)),
    }
    datablocks = sum(
        len(c)
        for c in (
            bpy.data.objects,
            bpy.data.meshes,
            bpy.data.materials,
            bpy.data.collections,
            bpy.data.node_groups,
            bpy.data.images,
            bpy.data.texts,
            bpy.data.scenes,
        )
    )
    return {
        "sizes": {
            "manifest entries": len(manifest.entries),
            "objects": len(bpy.data.objects),
            "meshes": len(bpy.data.meshes),
            "materials": len(bpy.data.materials),
            "datablocks of those kinds and collections, node groups, images, texts, scenes": datablocks,
        },
        "timings": timings,
    }
