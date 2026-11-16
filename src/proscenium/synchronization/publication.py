"""Publication: the whole generation switched together, or not at all (pipeline.md#synchronization-transaction).

A publication links the prepared objects into the destination and unlinks the published ones whose partitions they
replace or that the plan no longer has, updates the kept copies that change in place (local_updates), writes the
manifest by entry, only the entries the synchronization changed or removed, and writes the generation record. A failure
at any of these undoes those before it, in reverse, so the generation record, the manifest, the destination's links, and
every kept copy are all as before, or all absent on a first synchronization (TXN-06); the transaction then disposes of
the prepared work. What it would write unchanged it doesn't write, so a refresh that changes nothing writes nothing
(AFF-03).

It hands retirement the obsolete resources, those the old manifest names and the new one doesn't, which the attempt
holds until retirement removes them: the ledger records only those it can't.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..binding.persistence import binding_state, manifests
from ..binding.runtime import kept_manifests
from . import local_updates

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping, Sequence

    import bpy

    from ..core import _core
    from .preparation_resources import PreparationResources


@dataclass(frozen=True, slots=True)
class Publication:
    """What a publication did."""

    obsolete_entries: Mapping[str, manifests.ManifestEntry]  # by entry key: the resources retirement removes
    changed: bool  # whether it wrote anything: a link, a kept copy, the manifest, or the generation record


def publish(
    destination: bpy.types.Collection,
    plan: _core.Plan,
    work: PreparationResources,
    replaced_entry_keys: Collection[str],
    updates: Sequence[local_updates.KeptCopyUpdate],
    generation: binding_state.GenerationMetadata,
    before: manifests.Manifest | None,
    previous: binding_state.GenerationMetadata | None,
) -> Publication:
    """Make work, complete, the binding's published generation, described by generation.

    The new manifest is before's entries but those under replaced_entry_keys, with work's prepared entries, which keep
    the key of the published entry with their identity, replacement bounds meshes included; updates are set on the
    kept copies, from plan, the generation's. before and previous are the destination's manifest and
    generation record as the transaction read them, or None where it has none. The obsolete resources are before's
    entries, by entry key, naming a datablock the new manifest doesn't. Raises what the failing step raised, having
    undone the steps before it.
    """
    published = manifests.Manifest({}) if before is None else before
    changed = work.manifest_entries.keys()
    removed = {key for key in replaced_entry_keys if key in published.entries and key not in changed}
    entries = {key: e for key, e in published.entries.items() if key not in removed} | work.manifest_entries
    current = {e.datablock for e in entries.values()}
    obsolete = {
        entry_key: e
        for entry_key, e in published.entries.items()
        if e.datablock is not None and e.datablock not in current
    }
    leaving = {e.datablock for e in obsolete.values()}
    old = [obj for obj in destination.objects if obj in leaving]
    undo: list[Callable[[], object]] = []
    try:
        for obj in () if work.staging_collection is None else work.staging_collection.objects:
            destination.objects.link(obj)
            undo.append(functools.partial(destination.objects.unlink, obj))
        for obj in old:
            destination.objects.unlink(obj)
            undo.append(functools.partial(destination.objects.link, obj))
        local_updates.apply_updates(plan, updates, undo)
        if before is None or changed or removed:
            kept_manifests.write_manifest_entries(destination, manifests.Manifest(entries), changed, removed)
            if before is None:
                undo.append(functools.partial(kept_manifests.remove_manifest, destination))
            else:
                undo.append(functools.partial(kept_manifests.write_manifest, destination, before))
        if generation != previous:
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
    return Publication(obsolete, bool(undo))  # each write has its undo
