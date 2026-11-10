"""Prepared work: what a preparation has made, held by the attempt (pipeline.md#synchronization-transaction).

The application layer holds each resource it creates (PreparationResources.track) before anything else can fail, so
a failure partway finds everything made so far to dispose of (TXN-08). Resources reused from the published generation
are never held, so they're never disposal candidates (TXN-09). A cache call also changes published resources, adding
keys, and holds how to undo each change before making it (PreparationResources.rollback_actions), so a failure partway
reverts them all (CACHE-03).

dispose removes the held resources through datablock_removal.remove_unused, as retirement and a cleanup retry do,
users first, the staging collection aside. Only one whose removal fails, or whose user's did, enters the cleanup ledger,
retryable, with a cleanup diagnostic naming its ledger key, which no later attempt erases; a disposal that removes
everything writes nothing. One something else uses, as nothing should, is released intact.

The staging collection isn't a resource: nothing uses it, so it isn't saved, and disposal or publication removes it.
A leftover stays alive through the ledger's pointer to it, which is a user, linked in no collection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import bpy

from ..binding.persistence import cleanup_ledgers, id_property_records
from ..binding.results import Diagnostic, DiagnosticCode
from ..binding.runtime import pending_cleanup
from . import datablock_removal

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..binding.persistence import manifests
    from ..binding.source_access import BindingId


@dataclass
class PreparationResources:
    """Track staged resources and rollback callbacks for changes to published resources."""

    binding_id: BindingId  # the binding preparing it, which owns it
    operation: cleanup_ledgers.OriginatingOperation
    staging_collection: bpy.types.Collection  # holds the prepared objects; no scene links it
    datablocks: dict[str, bpy.types.ID] = field(default_factory=dict)  # entry key -> datablock, in creation order
    roles: dict[str, manifests.RepresentationRole] = field(default_factory=dict)  # entry key -> its datablock's role
    manifest_entries: dict[str, manifests.ManifestEntry] = field(
        default_factory=dict
    )  # entry key -> its entry, once complete
    rollback_actions: list[Callable[[], object]] = field(
        default_factory=list
    )  # undoes each change to a published resource

    def track(self, entry_key: str, role: manifests.RepresentationRole, datablock: bpy.types.ID) -> None:
        """Hold a resource just created, before anything else can fail."""
        self.datablocks[entry_key] = datablock
        self.roles[entry_key] = role


def cleanup_tracking_diagnostic(binding_id: BindingId) -> Diagnostic | None:
    """Report why the ledger cannot track failed disposal, or None when preparation can proceed."""
    try:
        pending_cleanup.check_trackable()
    except id_property_records.RefusedRecordError as error:
        return Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, error.refused.message)
    except ValueError as error:
        return Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, str(error))
    return None


def new_preparation_resources(
    binding_id: BindingId, operation: cleanup_ledgers.OriginatingOperation
) -> PreparationResources:
    """Create resource tracking for binding_id and its unlinked staging collection.

    Raises as pending_cleanup.check_trackable does, having made nothing: work whose failed disposal the ledger couldn't
    record is never prepared.
    """
    pending_cleanup.check_trackable()
    return PreparationResources(binding_id, operation, bpy.data.collections.new("Proscenium prepared"))


def dispose(work: PreparationResources) -> tuple[Diagnostic, ...]:
    """Remove what work holds, its staging collection included; a cleanup diagnostic for each removal that failed.

    Each that failed enters the ledger, retryable, with its diagnostic. Raises what writing the ledger raises.
    """
    outcome = datablock_removal.remove_unused(work.datablocks, holders=[work.staging_collection])
    pending: dict[str, cleanup_ledgers.LedgerEntry] = {}
    for entry_key, problem in outcome.pending_reasons_by_key.items():
        datablock, role = work.datablocks[entry_key], work.roles[entry_key]
        ledger_key = cleanup_ledgers.new_ledger_key()
        message = f"Couldn't dispose of prepared {role} {datablock.name!r}: {problem}"
        diagnostic = Diagnostic(
            DiagnosticCode.DISPOSAL_FAILED, work.binding_id, message, pending_resource_key=ledger_key, role=str(role)
        )
        pending[ledger_key] = cleanup_ledgers.LedgerEntry(
            work.binding_id, entry_key, role, datablock, work.operation, diagnostic
        )
    try:
        pending_cleanup.set_ledger_entries(pending)
    finally:
        remove_staging_and_clear_tracking(work)  # whatever the ledger records, the staging collection isn't a resource
    return tuple(e.diagnostic for e in pending.values())


def revert_published_resource_changes(work: PreparationResources) -> None:
    """Undo work's changes to published resources, in reverse, before disposing of it.

    Raises the first undo that failed, as a defect, having tried the rest, with the others' failures as notes.
    """
    failed: list[Exception] = []
    for step in reversed(work.rollback_actions):
        try:
            step()
        except Exception as error:  # noqa: BLE001 - the rest is still undone, and the first failure raised
            failed.append(error)
    work.rollback_actions.clear()
    if failed:
        for other in failed[1:]:
            failed[0].add_note(f"Another undo also failed: {other}")
        raise failed[0]


def remove_staging_and_clear_tracking(work: PreparationResources) -> None:
    """Remove the staging collection and clear resource tracking and rollback callbacks."""
    bpy.data.batch_remove([work.staging_collection])
    work.datablocks.clear()
    work.roles.clear()
    work.manifest_entries.clear()
    work.rollback_actions.clear()
