"""Retrying the cleanup an earlier attempt left pending (lifecycle.md#pending-cleanup).

A retry is explicit and needs no USD access: it reads a binding's entries from the ledger, whose pointers find the
leftovers, after reopening too (PEND-01), and removes them as disposal and retirement do (removal.remove_unused), which
revalidates each one's current users (PEND-02), the ledger's Text aside: one anything else uses is released intact,
and one whose removal fails, or whose user's did, stays retryable with a fresh cleanup diagnostic.

Each resolved entry leaves the ledger with its diagnostic (PEND-03, DIAG-08). Every entry of the binding is retried,
since no operation runs beside a retry (CONS-04). The result reports what's still pending; it's a fatal failure when
nothing could be resolved, as lifecycle.md's cleanup reports one. A ledger that can't be read refuses, disposing of
nothing (SCHEMA-06).
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from ..binding.persistence import configs, ledgers, records
from ..binding.results import Diagnostic, DiagnosticCode, Result
from ..binding.runtime import pending_cleanup
from . import removal

if TYPE_CHECKING:
    from ..binding.source_access import identifiers


def retry_cleanup(binding_id: identifiers.BindingId) -> Result:
    """Retry the binding's pending cleanup, disposing of or releasing each leftover; what's still pending."""
    try:
        ledger = pending_cleanup.ledger()
    except ValueError as error:  # two binding indexes: neither ledger authorizes disposal
        return Result(Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, str(error)))
    if isinstance(ledger, records.RefusedRecord):
        return Result(Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, ledger.message))
    entries = {} if ledger is None else {k: e for k, e in ledger.record.entries.items() if e.binding_id == binding_id}
    if not entries:
        return Result()
    [text] = configs.index_texts()  # the ledger's, one of each leftover's users
    outcome = removal.remove_unused({key: e.datablock for key, e in entries.items()}, holders=[text])
    resolved = sorted(outcome.removed_keys | outcome.released_keys)
    changed = {key: _pending(entries[key], key, problem) for key, problem in outcome.pending_reasons_by_key.items()}
    pending_cleanup.set_ledger_entries(changed, resolved)  # a failure is a defect, and raises
    diagnostics = [e.diagnostic for e in changed.values()]
    if changed and not resolved:
        message = f"Retrying binding {binding_id}'s pending cleanup resolved none of it"
        diagnostics.insert(0, Diagnostic(DiagnosticCode.CLEANUP_FAILED, binding_id, message))
    return Result(*diagnostics)


def _pending(entry: ledgers.LedgerEntry, ledger_key: str, problem: str) -> ledgers.LedgerEntry:
    """Entry with a fresh diagnostic saying why it's still pending, under its original code."""
    assert entry.datablock is not None
    message = f"Couldn't remove pending {entry.role} {entry.datablock.name!r}: {problem}"
    diagnostic = Diagnostic(
        entry.diagnostic.code, entry.binding_id, message, pending_resource_key=ledger_key, role=str(entry.role)
    )
    return dataclasses.replace(entry, diagnostic=diagnostic)
