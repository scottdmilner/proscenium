"""Retirement: removing the resources a publication made obsolete (pipeline.md#synchronization-transaction).

Publication has already taken each out of the manifest and the destination, and marked it in the ledger, so removing
one touches no manifest and no claim: a retirement costs what it removes. Each removed has its entry resolved. One whose
removal fails stays in the ledger, retryable, with a cleanup diagnostic naming its ledger key: noncanonical, since no
manifest names it, linked in no collection, and kept alive by the ledger's pointer. A failure never fails the
synchronization, which completes with issues (TXN-07).

Resources are retired in levels, by the old manifest's uses: first those no other obsolete resource uses, then those
only the first level used, and so on. Each level is removed in one call unless one fails (removal.remove), so a
retirement costs a call per level, not per resource.

- One whose user couldn't be retired stays pending too, untouched, so no leftover loses what it uses.
- One anything else uses is left intact and released from management (lifecycle.md#ownership-and-lifecycle): its entry
  is resolved, so no retry deletes it. Its users say so: once publication unlinked it and the levels before it are
  retired, the ledger's pointer is its one user, unless unmanaged content uses it, another manifest names it (as a
  copied destination's does), it has a fake user, or a user of it was itself released.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from ..binding.persistence import ledgers, manifests
from ..binding.results import Diagnostic, DiagnosticCode
from ..binding.runtime import pending_cleanup
from . import removal

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    import bpy

    from ..binding.source_access import identifiers


def retire(
    binding_id: identifiers.BindingId, retiring: Mapping[str, ledgers.LedgerEntry], published: manifests.Manifest
) -> tuple[Diagnostic, ...]:
    """Remove the resources publication marked, by ledger key; a cleanup diagnostic for each left pending.

    published is the manifest they were published in, whose uses order them. Raises what writing the ledger raises.
    """
    ledger_keys = {entry.entry_key: ledger_key for ledger_key, entry in retiring.items()}
    dependents = manifests.dependents(published)
    changed: dict[str, ledgers.LedgerEntry] = {}
    resolved: list[str] = []
    pending: set[str] = set()  # entry keys

    def leave_pending(entry_key: str, problem: object) -> None:
        ledger_key = ledger_keys[entry_key]
        entry = retiring[ledger_key]
        assert entry.datablock is not None
        message = f"Couldn't retire obsolete {entry.role} {entry.datablock.name!r}: {problem}"
        diagnostic = Diagnostic(
            DiagnosticCode.RETIREMENT_FAILED, binding_id, message, resource=ledger_key, role=str(entry.role)
        )
        changed[ledger_key] = dataclasses.replace(entry, status=ledgers.RetryStatus.RETRYABLE, diagnostic=diagnostic)
        pending.add(entry_key)

    for level in _levels(dependents, ledger_keys.keys()):
        removing: list[tuple[str, bpy.types.ID]] = []
        for entry_key in level:
            datablock = retiring[ledger_keys[entry_key]].datablock
            if datablock is None:  # removed since publication: nothing is left to remove
                resolved.append(ledger_keys[entry_key])
            elif dependents[entry_key] & pending:
                leave_pending(entry_key, "a resource using it couldn't be retired")
            elif datablock.users > 1:  # something else uses it: released intact
                resolved.append(ledger_keys[entry_key])
            else:
                removing.append((entry_key, datablock))
        failures = removal.remove([datablock for _, datablock in removing])
        for index, (entry_key, _) in enumerate(removing):
            if (error := failures.get(index)) is not None:
                leave_pending(entry_key, error)
            else:
                resolved.append(ledger_keys[entry_key])
    pending_cleanup.set_ledger_entries(changed, resolved)
    return tuple(e.diagnostic for e in changed.values() if e.diagnostic is not None)


def _levels(dependents: Mapping[str, set[str]], entry_keys: Iterable[str]) -> list[list[str]]:
    """entry_keys in levels: each after every level holding one among them that uses it, each level sorted."""
    keys = set(entry_keys)
    depth: dict[str, int] = {}

    def level_of(entry_key: str) -> int:
        if entry_key not in depth:
            depth[entry_key] = 1 + max((level_of(user) for user in dependents[entry_key] & keys), default=-1)
        return depth[entry_key]

    levels: list[list[str]] = []
    for entry_key in sorted(keys):
        at = level_of(entry_key)
        levels.extend([] for _ in range(at + 1 - len(levels)))
        levels[at].append(entry_key)
    return levels
