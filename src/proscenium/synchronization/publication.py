"""Publication: the whole generation switched together, or not at all (pipeline.md#synchronization-transaction).

A publication links the prepared objects into the destination and unlinks the published generation's, and writes the
manifest whole and the generation record. A failure at any of these undoes those before it, in reverse, so the
generation record, the manifest, and the destination's links are all as before, or all absent on a first
synchronization (TXN-06); the transaction then disposes of the prepared work. Correspondence joins the switch with M7.

It hands retirement the obsolete resources, those the old manifest names and the new one doesn't, which the attempt
holds until retirement removes them: the ledger records only those it can't.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

from ..binding.persistence import binding_state, manifests

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    import bpy

    from .preparation_resources import PreparationResources


def publish(
    destination: bpy.types.Collection,
    work: PreparationResources,
    generation: binding_state.GenerationMetadata,
    before: manifests.Manifest | None,
    previous: binding_state.GenerationMetadata | None,
) -> Mapping[str, manifests.ManifestEntry]:
    """Make work, complete, the binding's published generation, described by generation; the obsolete resources.

    before and previous are the destination's manifest and generation record as the transaction read them, or None
    where it has none. The obsolete resources are before's entries, by entry key, naming a datablock the new manifest
    doesn't. Raises what the failing step raised, having undone the steps before it.
    """
    published = manifests.Manifest({}) if before is None else before
    named = {e.datablock for e in published.entries.values()}
    old = [obj for obj in destination.objects if obj in named]
    current = {e.datablock for e in work.manifest_entries.values()}
    obsolete = {
        entry_key: e
        for entry_key, e in published.entries.items()
        if e.datablock is not None and e.datablock not in current
    }
    undo: list[Callable[[], object]] = []
    try:
        for obj in work.staging_collection.objects:
            destination.objects.link(obj)
            undo.append(functools.partial(destination.objects.unlink, obj))
        for obj in old:
            destination.objects.unlink(obj)
            undo.append(functools.partial(destination.objects.link, obj))
        manifests.write_manifest(destination, manifests.Manifest(work.manifest_entries))
        if before is None:
            undo.append(functools.partial(manifests.remove_manifest, destination))
        else:
            undo.append(functools.partial(manifests.write_manifest, destination, before))
        binding_state.write_generation(destination, generation)
        if previous is None:
            undo.append(functools.partial(binding_state.remove_generation, destination))
        else:
            undo.append(functools.partial(binding_state.write_generation, destination, previous))
    except Exception as error:
        for step in reversed(undo):
            try:
                step()
            except Exception as undo_error:  # noqa: BLE001 - the rest is still undone, and the first failure raised
                error.add_note(f"Undoing publication also failed: {undo_error}")
        raise
    return obsolete
