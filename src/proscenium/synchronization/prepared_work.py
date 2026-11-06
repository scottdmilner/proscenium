"""Prepared work: what a preparation has made, held by the attempt (pipeline.md#synchronization-transaction).

The application layer holds each resource it creates (PreparedWork.track) before anything else can fail, so a failure
partway finds everything made so far to dispose of (TXN-08). Resources reused from the published generation are never
held, so they're never disposal candidates (TXN-09).

dispose removes the held resources, in one call unless one fails (removal.remove). Only one whose removal fails enters
the pending-cleanup ledger, retryable, with a cleanup diagnostic naming its ledger key, which no later attempt erases; a
disposal that removes everything writes nothing.

The staging collection isn't a resource: nothing uses it, so it isn't saved, and disposal or publication removes it.
A leftover stays alive through the ledger's pointer to it, which is a user, linked in no collection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import bpy

from ..binding.persistence import ledgers
from ..binding.results import Diagnostic, DiagnosticCode
from ..binding.runtime import pending_cleanup
from . import removal

if TYPE_CHECKING:
    from ..binding.persistence import manifests
    from ..binding.source_access import identifiers


@dataclass
class PreparedWork:
    """What a preparation has made so far, so a failure partway leaves it all to dispose of."""

    binding_id: identifiers.BindingId  # the binding preparing it, which owns it
    operation: ledgers.OriginatingOperation
    staging: bpy.types.Collection  # holds the prepared objects; no scene links it
    datablocks: dict[str, bpy.types.ID] = field(default_factory=dict)  # entry key -> datablock, in creation order
    roles: dict[str, manifests.RepresentationRole] = field(default_factory=dict)  # entry key -> its datablock's role
    entries: dict[str, manifests.ManifestEntry] = field(default_factory=dict)  # entry key -> its entry, once complete

    def track(self, entry_key: str, role: manifests.RepresentationRole, datablock: bpy.types.ID) -> None:
        """Hold a resource just created, before anything else can fail."""
        self.datablocks[entry_key] = datablock
        self.roles[entry_key] = role


def new_prepared_work(binding_id: identifiers.BindingId, operation: ledgers.OriginatingOperation) -> PreparedWork:
    """Empty prepared work for binding_id, with its staging collection.

    Raises as pending_cleanup.check_trackable does, having made nothing: work whose failed disposal the ledger couldn't
    record is never prepared.
    """
    pending_cleanup.check_trackable()
    return PreparedWork(binding_id, operation, bpy.data.collections.new("Proscenium prepared"))


def dispose(work: PreparedWork) -> tuple[Diagnostic, ...]:
    """Remove what work holds, its staging collection included; a cleanup diagnostic for each removal that failed.

    Each that failed enters the ledger, retryable, with its diagnostic. Raises what writing the ledger raises.
    """
    made = list(reversed(work.datablocks.items()))  # users before what they use
    failures = removal.remove([datablock for _, datablock in made])
    pending: dict[str, ledgers.LedgerEntry] = {}
    for index, (entry_key, datablock) in enumerate(made):
        if (error := failures.get(index)) is None:
            continue
        role = work.roles[entry_key]
        ledger_key = ledgers.new_ledger_key()
        message = f"Couldn't dispose of prepared {role} {datablock.name!r}: {error}"
        diagnostic = Diagnostic(
            DiagnosticCode.DISPOSAL_FAILED, work.binding_id, message, resource=ledger_key, role=str(role)
        )
        pending[ledger_key] = ledgers.LedgerEntry(
            work.binding_id, entry_key, role, datablock, work.operation, diagnostic
        )
    try:
        pending_cleanup.set_ledger_entries(pending)
    finally:
        remove_staging(work)  # whatever the ledger records, the staging collection isn't a resource
    return tuple(e.diagnostic for e in pending.values())


def remove_staging(work: PreparedWork) -> None:
    """Remove work's staging collection and let go of what it held: published, or disposed of."""
    bpy.data.batch_remove([work.staging])
    work.datablocks.clear()
    work.roles.clear()
    work.entries.clear()
