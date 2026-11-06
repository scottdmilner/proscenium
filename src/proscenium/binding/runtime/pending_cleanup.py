"""The pending-cleanup ledger, through the bindings' state (lifecycle.md#pending-cleanup).

The ledger is read from the binding index's Text when first asked for, and held with that Text's records; writes go
through it, as manifest writes do. Every operation's result reports its binding's cleanup status from it, so once it's
held a result costs a check of each entry's datablock, and only work it records or resolves writes it.

While the file has more than one binding index, the ledger refuses as the index does: an appended index Text brings a
ledger whose pointers name the appended copies, so nothing is recorded or disposed of until it's gone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..persistence import ledgers, records
from . import state
from .state import StaleError, Unread

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from .. import results
    from ..source_access import identifiers
    from .state import IndexRecords, State


def ledger() -> records.Loaded[ledgers.Ledger] | records.RefusedRecord | None:
    """The file's pending-cleanup ledger, why it can't be read, or None if there is none yet.

    Raises ValueError if the file has more than one binding index.
    """
    return state.query(_checked_ledger)


def cleanup_status(binding_id: identifiers.BindingId) -> tuple[results.Diagnostic, ...]:
    """The binding's current cleanup diagnostics: the ledger's, one per resource it holds pending, by ledger key.

    A ledger entry is one resource with one originating operation, so these are deduplicated by operation and resource
    (DIAG-06). Prepared work, still tracked by the operation preparing it, has none. Empty when the ledger can't be read
    or the file has more than one binding index, since neither names a pending resource cleanup could retry.
    """

    def question(current: State) -> tuple[results.Diagnostic, ...]:
        if len(current.indexes) > 1 or not isinstance(ledger := _checked_ledger(current), records.Loaded):
            return ()
        entries = sorted(ledger.record.entries.items())
        return tuple(e.diagnostic for _, e in entries if e.binding_id == binding_id and e.diagnostic is not None)

    return state.query(question)


def nothing_pending(binding_id: identifiers.BindingId) -> bool:
    """Whether the ledger can be read and holds no entry of the binding, so a retry has nothing to do or report."""

    def question(current: State) -> bool:
        if len(current.indexes) > 1 or isinstance(ledger := _checked_ledger(current), records.RefusedRecord):
            return False
        return ledger is None or all(e.binding_id != binding_id for e in ledger.record.entries.values())

    return state.query(question)


def set_ledger_entries(changed: Mapping[str, ledgers.LedgerEntry], removed: Collection[str] = ()) -> None:
    """Change some of the ledger's entries, writing only those; a file with no ledger yet starts from an empty one.

    An empty update writes nothing. Raises as check_trackable does, and ValueError or TypeError, changing nothing, over
    an update that makes no ledger.
    """
    held = _trackable()
    if not changed and not removed:
        return
    stored = _ledger_of(held)
    assert not isinstance(stored, records.RefusedRecord)  # _trackable refused it
    after = (ledgers.Ledger({}) if stored is None else stored.record).updated(changed, removed)
    held.ledger = ledgers.write_ledger_entries(held.text, after, changed.keys(), removed)


def check_trackable() -> None:
    """Raise unless the ledger can record work.

    RefusedRecordError over one that can't be read, and ValueError if the file has no binding index to hold it or more
    than one.
    """
    _trackable()


def _trackable() -> IndexRecords:
    """The index Text's records, holding a ledger that can be read or none yet; raises as check_trackable does."""
    held = state.query(_held_index)
    if held is None:
        raise ValueError("This file has no binding index to hold the pending-cleanup ledger")
    if isinstance(stored := _ledger_of(held), records.RefusedRecord):
        raise records.RefusedRecordError(stored)
    return held


def _checked_ledger(current: State) -> records.Loaded[ledgers.Ledger] | records.RefusedRecord | None:
    """The ledger, reread if a datablock it names was removed: Blender cleared that entry's pointer."""
    if (held := _held_index(current)) is None:
        return None
    ledger = _ledger_of(held)
    if isinstance(ledger, records.Loaded) and not all(
        e.datablock is None or state.alive(e.datablock) for e in ledger.record.entries.values()
    ):
        held.ledger = ledger = ledgers.read_ledger(held.text)
    return ledger


def _held_index(current: State) -> IndexRecords | None:
    """The records on the file's only binding index Text, or None if it has none; ValueError if it has more."""
    if len(current.indexes) > 1:
        raise ValueError(f"This file has {len(current.indexes)} binding indexes")
    if not current.indexes:
        return None
    held = current.indexes[0]
    if not state.alive(held.text):
        raise StaleError  # removed since the state was built
    return held


def _ledger_of(held: IndexRecords) -> records.Loaded[ledgers.Ledger] | records.RefusedRecord | None:
    """The Text's ledger, read the first time."""
    if isinstance(held.ledger, Unread):
        held.ledger = ledgers.read_ledger(held.text)
    return held.ledger
