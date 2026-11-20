"""Removing a binding: its managed content, then its configuration (lifecycle.md#ownership-and-lifecycle, OWN-14).

Removal needs no USD access. It refuses, changing nothing, while a record it would remove or the pending-cleanup ledger
can't be read (lifecycle.md#schema-versions). Otherwise it commits, in this order:

1. The binding's managed content, those its manifest names and its own leftovers in the ledger, goes through
   datablock_removal.remove_unused, as disposal, retirement, and a cleanup retry do, with the destination and the
   ledger's Text as the operation's own holders. One anything else uses, unmanaged content or another binding's
   manifest, is released intact (OWN-15). Its objects are unlinked from the destination first, as publication unlinks
   what retirement removes, so a view layer's base isn't taken for a use, and each one released is linked again.
2. Each removal that fails, or whose user's did, stays in the ledger, retryable, with a cleanup diagnostic among the
   result's, so the removal completes with issues: a resource the manifest named enters it with a removal-failed
   diagnostic, and a leftover gets a fresh diagnostic under its own code, as a retry gives it. An object stays
   unlinked, so it's inactive. The ledger is
   on the binding index's Text, which outlives the configuration, so no disposal work is orphaned
   (lifecycle.md#lifecycle-failure-safety). A ledger write that fails raises, as a defect.
3. The destination is removed, which takes the binding's records with it, when it then holds nothing and nothing but
   the collections and scenes linking it, and the binding index's entry, uses it. Otherwise the binding's records are
   removed from it, and it stays, an ordinary collection, with the unmanaged content linked into it and any content
   released intact (OWN-07).

The binding index's entry stays on its Text, as a removed destination's does (lifecycle.md#removed-destination).
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import bpy

from proscenium_sync.persistence import binding_records, binding_state, cleanup_ledgers, id_property_records, manifests
from proscenium_sync.results import Diagnostic, DiagnosticCode, Result
from proscenium_sync.runtime import kept_manifests, pending_cleanup

from . import cleanup_retry, datablock_removal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from proscenium_sync.runtime.binding_operations import FoundBinding
    from proscenium_sync.source_access import BindingId


@dataclasses.dataclass(frozen=True, slots=True)
class RemovalOutcome:
    """A removal's result, and whether it committed, so it's an undo step and the binding is gone."""

    result: Result
    committed: bool  # false only for a refusal, which changes nothing


def remove_binding(found: FoundBinding) -> RemovalOutcome:
    """Remove a binding the caller has found usable: its managed content, then its records."""
    binding_id, destination = found.binding_id, found.destination
    assert destination is not None  # a usable binding's
    if isinstance(checked := _checked_records(binding_id, destination), Diagnostic):
        return RemovalOutcome(Result(checked), committed=False)
    manifest, ledger, text = checked
    managed = {("manifest", key): e.datablock for key, e in manifest.entries.items()}
    mine = {key: e for key, e in ledger.entries.items() if e.binding_id == binding_id}
    leftovers = {("ledger", key): e.datablock for key, e in mine.items()}
    # Unlinked first, as publication unlinks what retirement removes, so a view layer's base isn't taken for a use.
    linked = _unlink_managed_objects(destination, managed)
    outcome = datablock_removal.remove_unused(managed | leftovers, holders=[destination, text])
    for key in sorted(outcome.released_keys & linked.keys()):
        destination.objects.link(linked[key])  # released intact, links included
    resolved = sorted(key for kind, key in outcome.removed_keys | outcome.released_keys if kind == "ledger")
    pending: dict[str, cleanup_ledgers.LedgerEntry] = {}  # new and refreshed entries, by ledger key
    for (kind, key), problem in sorted(outcome.pending_reasons_by_key.items()):
        if kind == "ledger":  # a leftover that fails again, as a retry reports it
            pending[key] = cleanup_retry.still_pending(mine[key], key, problem)
            continue
        entry = _pending_entry(binding_id, key, manifest.entries[key], problem)
        pending[entry.diagnostic.pending_resource_key] = entry
    pending_cleanup.set_ledger_entries(pending, resolved)  # a failure is a defect, and raises
    kept_manifests.remove_manifest(destination)  # the record, and the entry kept by the destination's session uid
    if not _remove_destination(destination, text):
        _remove_records(binding_id, destination)
    diagnostics = [e.diagnostic for _, e in sorted(pending.items())]
    return RemovalOutcome(Result(*diagnostics), committed=True)


def _checked_records(
    binding_id: BindingId, destination: bpy.types.Collection
) -> tuple[manifests.Manifest, cleanup_ledgers.Ledger, bpy.types.Text] | Diagnostic:
    """The manifest, the ledger, and its Text; or why one of those, or a record removal deletes, can't be read.

    An empty manifest for a binding with none yet, and an empty ledger for a file with none yet.
    """
    try:
        text, stored = pending_cleanup.trackable_ledger()
    except ValueError as error:  # no binding index, or two: neither ledger authorizes disposal
        return Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, str(error))
    except id_property_records.RefusedRecordError as error:
        return Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, error.refused.message)
    manifest = kept_manifests.read_manifest(destination)
    for record in (manifest, binding_state.read_generation(destination), binding_state.read_last_attempt(destination)):
        if isinstance(record, id_property_records.RefusedRecord):
            return Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, record.message)
    assert not isinstance(manifest, id_property_records.RefusedRecord)  # refused above
    ledger = cleanup_ledgers.Ledger({}) if stored is None else stored.record
    return manifests.Manifest({}) if manifest is None else manifest.record, ledger, text


def _unlink_managed_objects[K](
    destination: bpy.types.Collection, managed: Mapping[K, bpy.types.ID | None]
) -> dict[K, bpy.types.Object]:
    """Unlink the managed objects linked into the destination; those unlinked, by key."""
    in_destination = {o.session_uid for o in destination.objects}
    linked = {
        key: d
        for key, d in managed.items()
        if isinstance(d, bpy.types.Object) and id_property_records.alive(d) and d.session_uid in in_destination
    }
    for obj in linked.values():
        destination.objects.unlink(obj)
    return linked


def _pending_entry(
    binding_id: BindingId, entry_key: str, entry: manifests.ManifestEntry, problem: str
) -> cleanup_ledgers.LedgerEntry:
    """The ledger entry of a managed resource the removal couldn't remove, with its cleanup diagnostic."""
    assert entry.datablock is not None  # one gone counts as removed
    ledger_key = cleanup_ledgers.new_ledger_key()
    message = f"Couldn't remove managed {entry.role} {entry.datablock.name!r}: {problem}"
    diagnostic = Diagnostic(
        DiagnosticCode.REMOVAL_FAILED, binding_id, message, pending_resource_key=ledger_key, role=str(entry.role)
    )
    operation = cleanup_ledgers.OriginatingOperation.REMOVE
    return cleanup_ledgers.LedgerEntry(binding_id, entry_key, entry.role, entry.datablock, operation, diagnostic)


def _remove_destination(destination: bpy.types.Collection, text: bpy.types.Text) -> bool:
    """Remove the destination if it holds nothing and only what links it uses it; whether it's gone.

    The binding index's Text, whose entry names it, isn't a use.
    """
    if destination.objects or destination.children:
        return False
    holders: list[bpy.types.ID] = [text]
    holders += [c for c in bpy.data.collections if destination in c.children.values()]
    holders += [s for s in bpy.data.scenes if destination in s.collection.children.values()]
    outcome = datablock_removal.remove_unused({"destination": destination}, holders=holders)
    return outcome.removed_keys == {"destination"}


def _remove_records(binding_id: BindingId, destination: bpy.types.Collection) -> None:
    """Remove the binding's remaining records from the destination it leaves behind.

    Each was read first, so none raises; the manifest is already gone.
    """
    binding_state.remove_generation(destination)
    binding_state.remove_last_attempt(destination)
    binding_records.remove_config(destination, binding_id)
