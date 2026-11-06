"""Retirement: removing the resources a publication made obsolete (pipeline.md#synchronization-transaction).

Publication has already taken each out of the manifest and the destination, and handed it here, so removing one
touches no manifest and no claim: a retirement costs what it removes. Only one whose removal fails enters the ledger,
retryable, with a cleanup diagnostic naming its ledger key: noncanonical, since no manifest names it, linked in no
collection, and kept alive by the ledger's pointer. A failure never fails the synchronization, which completes with
issues (TXN-07).

Resources are retired in levels, by the old manifest's uses: first those no other obsolete resource uses, then those
only the first level used, and so on. Each level is removed in one call unless one fails (removal.remove), so a
retirement costs a call per level, not per resource.

- One whose user couldn't be retired stays pending too, untouched, so no leftover loses what it uses.
- One anything else uses is left intact and released from management (lifecycle.md#ownership-and-lifecycle), with no
  ledger entry, so no retry deletes it. Its users say so: once publication unlinked it and replaced the manifest, and
  the levels before it are retired, it has none, unless unmanaged content uses it, another manifest names it (as a
  copied destination's does), it has a fake user, or a user of it was itself released.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..binding.persistence import ledgers, manifests
from ..binding.results import Diagnostic, DiagnosticCode
from ..binding.runtime import pending_cleanup, state
from . import removal

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    import bpy

    from ..binding.source_access import identifiers


def retire(
    binding_id: identifiers.BindingId,
    obsolete: Mapping[str, manifests.ManifestEntry],
    published: manifests.Manifest,
    operation: ledgers.OriginatingOperation,
) -> tuple[Diagnostic, ...]:
    """Remove the obsolete resources publication handed over, by entry key; a cleanup diagnostic for each left pending.

    published is the manifest they were published in, whose uses order them; each left pending enters the ledger as
    operation's. Raises what writing the ledger raises.
    """
    dependents = manifests.dependents(published)
    pending: dict[str, ledgers.LedgerEntry] = {}  # by ledger key
    left: set[str] = set()  # entry keys

    def leave_pending(entry_key: str, datablock: bpy.types.ID, problem: object) -> None:
        role = obsolete[entry_key].role
        ledger_key = ledgers.new_ledger_key()
        message = f"Couldn't retire obsolete {role} {datablock.name!r}: {problem}"
        diagnostic = Diagnostic(
            DiagnosticCode.RETIREMENT_FAILED, binding_id, message, resource=ledger_key, role=str(role)
        )
        pending[ledger_key] = ledgers.LedgerEntry(binding_id, entry_key, role, datablock, operation, diagnostic)
        left.add(entry_key)

    for level in _levels(dependents, obsolete.keys()):
        removing: list[tuple[str, bpy.types.ID]] = []
        for entry_key in level:
            datablock = obsolete[entry_key].datablock
            if datablock is None or not state.alive(datablock):  # removed since publication: nothing to remove
                continue
            if dependents[entry_key] & left:
                leave_pending(entry_key, datablock, "a resource using it couldn't be retired")
            elif datablock.users > 0:  # something else uses it: released intact
                continue
            else:
                removing.append((entry_key, datablock))
        failures = removal.remove([datablock for _, datablock in removing])
        for index, (entry_key, datablock) in enumerate(removing):
            if (error := failures.get(index)) is not None:
                leave_pending(entry_key, datablock, error)
    pending_cleanup.set_ledger_entries(pending)
    return tuple(e.diagnostic for e in pending.values())


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
