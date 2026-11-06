"""Retrying the cleanup an earlier attempt left pending (lifecycle.md#pending-cleanup).

A retry is explicit and needs no USD access: it reads a binding's entries from the ledger, whose pointers find the
leftovers, after reopening too (PEND-01), and revalidates each one's current users (PEND-02):

- One whose only users are the ledger and other leftovers removed before it is removed, a level at a time, users
  first, each level in one call unless one fails (removal.remove).
- One anything else uses is left intact and released from management: unmanaged content, a manifest naming it, which
  makes the manifest's datablock a user, a fake user, or a leftover itself released.
- One whose removal fails, or whose user's did, stays retryable with a fresh cleanup diagnostic.

Each resolved entry leaves the ledger with its diagnostic (PEND-03, DIAG-08). Every entry of the binding is retried,
since no operation runs beside a retry (CONS-04). The result reports what's still pending; it's a fatal failure when
nothing could be resolved, as lifecycle.md's cleanup reports one. A ledger that can't be read refuses, disposing of
nothing (SCHEMA-06).
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import bpy

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
    resolved, pending = _retried(entries, text)
    changed = {key: _pending(entries[key], key, problem) for key, problem in pending.items()}
    try:
        pending_cleanup.set_ledger_entries(changed, resolved)
    except Exception as error:  # noqa: BLE001 - reported, never raised
        message = f"Couldn't record the retry in the pending-cleanup ledger: {error}"
        return Result(Diagnostic(DiagnosticCode.CLEANUP_FAILED, binding_id, message))
    diagnostics = [e.diagnostic for e in changed.values()]
    if changed and not resolved:
        message = f"Retrying binding {binding_id}'s pending cleanup resolved none of it"
        diagnostics.insert(0, Diagnostic(DiagnosticCode.CLEANUP_FAILED, binding_id, message))
    return Result(*diagnostics)


def _retried(entries: dict[str, ledgers.LedgerEntry], text: bpy.types.Text) -> tuple[list[str], dict[str, str]]:
    """Dispose of or release each entry's leftover; the ledger keys resolved, and why each other is still pending."""
    resolved = [key for key, e in entries.items() if e.datablock is None]  # removed already: nothing to retry
    leftovers = {key: e.datablock for key, e in entries.items() if e.datablock is not None}
    key_of = {d.session_uid: key for key, d in leftovers.items()}
    # Each leftover's users other than the ledger, read before anything is removed, by session_uid.
    user_map = bpy.data.user_map(subset=list(leftovers.values()))
    users = {key: {u.session_uid for u in user_map[d]} - {text.session_uid} for key, d in leftovers.items()}
    removed: set[str] = set()
    released: set[str] = set()
    pending: dict[str, str] = {}
    undecided = set(leftovers)
    while undecided:
        level: list[str] = []
        for key in sorted(undecided):
            using = {key_of.get(uid) for uid in users[key]}
            if None in using or using & released:  # something besides its binding's leftovers uses it
                released.add(key)
            elif using & pending.keys():
                pending[key] = "a resource using it couldn't be removed"
            elif using <= removed:
                level.append(key)
        undecided -= released | pending.keys() | set(level)
        if not level:
            break
        failures = removal.remove([leftovers[key] for key in level])
        for index, key in enumerate(level):
            if (error := failures.get(index)) is not None:
                pending[key] = str(error)
            else:
                removed.add(key)
    for key in undecided:  # only leftovers using each other in a cycle are left
        pending[key] = "it and the leftovers using it use each other"
    return [*resolved, *sorted(removed | released)], pending


def _pending(entry: ledgers.LedgerEntry, ledger_key: str, problem: str) -> ledgers.LedgerEntry:
    """Entry with a fresh diagnostic saying why it's still pending, under its original code."""
    assert entry.datablock is not None
    message = f"Couldn't remove pending {entry.role} {entry.datablock.name!r}: {problem}"
    diagnostic = Diagnostic(entry.diagnostic.code, entry.binding_id, message, resource=ledger_key, role=str(entry.role))
    return dataclasses.replace(entry, diagnostic=diagnostic)
