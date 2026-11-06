"""Prepared work: what a preparation has made, tracked in the ledger (pipeline.md#synchronization-transaction).

The application layer tracks each resource it creates (PreparedWork.track) before anything else can fail, so a failure
partway finds everything made so far in the ledger (TXN-08). Resources reused from the published generation are never
tracked, so they're never disposal candidates (TXN-09).

dispose removes the tracked resources, in one call unless one fails (removal.remove), and resolves their ledger
entries. One whose removal fails stays in the ledger, retryable, with a cleanup diagnostic naming its ledger key, which
no later attempt erases.

The staging collection isn't a resource: nothing uses it, so it isn't saved, and disposal or publication removes it.
A leftover stays alive through the ledger's pointer to it, which is a user, linked in no collection.
"""

from __future__ import annotations

import dataclasses
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
    entries: dict[str, manifests.ManifestEntry] = field(default_factory=dict)  # entry key -> its entry, once complete
    tracked: dict[str, ledgers.LedgerEntry] = field(default_factory=dict)  # ledger key -> its entry, as recorded

    def track(self, entry_key: str, role: manifests.RepresentationRole, datablock: bpy.types.ID) -> None:
        """Hold a resource just created, and record it in the ledger, before anything else can fail.

        Raises what writing the ledger raises; the datablock is held first, so disposal still removes it.
        """
        self.datablocks[entry_key] = datablock
        ledger_key = ledgers.new_ledger_key()
        entry = ledgers.LedgerEntry(
            self.binding_id, entry_key, role, datablock, self.operation, ledgers.RetryStatus.PREPARED
        )
        pending_cleanup.set_ledger_entries({ledger_key: entry})
        self.tracked[ledger_key] = entry


def new_prepared_work(binding_id: identifiers.BindingId, operation: ledgers.OriginatingOperation) -> PreparedWork:
    """Empty prepared work for binding_id, with its staging collection.

    Raises as pending_cleanup.check_trackable does, having made nothing: work the ledger can't track is never prepared.
    """
    pending_cleanup.check_trackable()
    return PreparedWork(binding_id, operation, bpy.data.collections.new("Proscenium prepared"))


def dispose(work: PreparedWork) -> tuple[Diagnostic, ...]:
    """Remove what work holds, its staging collection included; a cleanup diagnostic for each removal that failed.

    Each resource removed has its ledger entry resolved; each that failed stays, retryable, with its diagnostic. Raises
    what writing the ledger raises.
    """
    keys = {entry.entry_key: ledger_key for ledger_key, entry in work.tracked.items()}
    changed: dict[str, ledgers.LedgerEntry] = {}
    resolved: list[str] = []
    diagnostics: list[Diagnostic] = []
    made = list(reversed(work.datablocks.items()))  # users before what they use
    failures = removal.remove([datablock for _, datablock in made])
    for index, (entry_key, datablock) in enumerate(made):
        ledger_key = keys.get(entry_key)
        role = "" if ledger_key is None else str(work.tracked[ledger_key].role)  # a diagnostic holds plain strings
        if (error := failures.get(index)) is not None:
            message = f"Couldn't dispose of prepared {role or 'resource'} {datablock.name!r}: {error}"
            diagnostic = Diagnostic(
                DiagnosticCode.DISPOSAL_FAILED, work.binding_id, message, resource=ledger_key or "", role=role
            )
            diagnostics.append(diagnostic)
            if ledger_key is not None:
                entry = work.tracked[ledger_key]
                changed[ledger_key] = dataclasses.replace(
                    entry, status=ledgers.RetryStatus.RETRYABLE, diagnostic=diagnostic
                )
            continue
        if ledger_key is not None:
            resolved.append(ledger_key)
    try:
        pending_cleanup.set_ledger_entries(changed, resolved)
    finally:
        remove_staging(work)  # whatever the ledger records, the staging collection isn't a resource
    return tuple(diagnostics)


def remove_staging(work: PreparedWork) -> None:
    """Remove work's staging collection and let go of what it held: published, or disposed of."""
    bpy.data.batch_remove([work.staging])
    work.datablocks.clear()
    work.entries.clear()
    work.tracked.clear()
