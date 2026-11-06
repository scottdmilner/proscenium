"""Retirement: removing the resources a publication made obsolete (pipeline.md#synchronization-transaction).

Publication has already taken each out of the manifest and the destination, and handed it here, so removing one
touches no manifest and no claim: a retirement costs what it removes. They're removed as disposal and a cleanup retry
remove (removal.remove_unused), users first, each level in one call unless one fails.

- One anything else uses is left intact and released from management (lifecycle.md#ownership-and-lifecycle), with no
  ledger entry, so no retry deletes it: unmanaged content, another manifest naming it (as a copied destination's does),
  a fake user, or a user of it itself released.
- Only one whose removal fails, or whose user's did, enters the ledger, retryable, with a cleanup diagnostic naming its
  ledger key: noncanonical, since no manifest names it, linked in no collection, and kept alive by the ledger's
  pointer. A failure never fails the synchronization, which completes with issues (TXN-07).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..binding.persistence import ledgers
from ..binding.results import Diagnostic, DiagnosticCode
from ..binding.runtime import pending_cleanup
from . import removal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..binding.persistence import manifests
    from ..binding.source_access import identifiers


def retire(
    binding_id: identifiers.BindingId,
    obsolete: Mapping[str, manifests.ManifestEntry],
    operation: ledgers.OriginatingOperation,
) -> tuple[Diagnostic, ...]:
    """Remove the obsolete resources publication handed over, by entry key; a cleanup diagnostic for each left pending.

    Each left pending enters the ledger as operation's. Raises what writing the ledger raises.
    """
    outcome = removal.remove_unused({entry_key: e.datablock for entry_key, e in obsolete.items()})
    pending: dict[str, ledgers.LedgerEntry] = {}  # by ledger key
    for entry_key, problem in sorted(outcome.pending.items()):
        datablock, role = obsolete[entry_key].datablock, obsolete[entry_key].role
        assert datablock is not None  # one gone counts as removed
        ledger_key = ledgers.new_ledger_key()
        message = f"Couldn't retire obsolete {role} {datablock.name!r}: {problem}"
        diagnostic = Diagnostic(
            DiagnosticCode.RETIREMENT_FAILED, binding_id, message, resource=ledger_key, role=str(role)
        )
        pending[ledger_key] = ledgers.LedgerEntry(binding_id, entry_key, role, datablock, operation, diagnostic)
    pending_cleanup.set_ledger_entries(pending)
    return tuple(e.diagnostic for e in pending.values())
