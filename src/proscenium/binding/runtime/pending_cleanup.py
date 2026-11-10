"""The pending-cleanup ledger, read from the binding index's Text when asked for (lifecycle.md#pending-cleanup).

Every operation's result reports its binding's cleanup status from it, and only work it records or resolves writes it.

While the file has more than one binding index, the ledger refuses as the index does: an appended index Text brings a
ledger whose pointers name the appended copies, so nothing is recorded or disposed of until it's gone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..persistence import binding_records, cleanup_ledgers, id_property_records

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    import bpy

    from .. import results
    from ..source_access import binding_ids


def ledger() -> id_property_records.LoadedRecord[cleanup_ledgers.Ledger] | id_property_records.RefusedRecord | None:
    """The file's pending-cleanup ledger, why it can't be read, or None if there is none yet.

    Raises ValueError if the file has more than one binding index.
    """
    text = _index_text()
    return None if text is None else cleanup_ledgers.read_ledger(text)


def cleanup_status(binding_id: binding_ids.BindingId) -> tuple[results.Diagnostic, ...]:
    """The binding's current cleanup diagnostics: the ledger's, one per resource it holds pending, by ledger key.

    A ledger entry is one resource with one originating operation, so these are deduplicated by operation and resource
    (DIAG-06). Prepared work is held by the operation preparing it, never in the ledger. Empty when the ledger can't be
    read or the file has more than one binding index, since neither names a pending resource cleanup could retry.
    """
    try:
        held = ledger()
    except ValueError:
        return ()
    if not isinstance(held, id_property_records.LoadedRecord):
        return ()
    return tuple(e.diagnostic for _, e in sorted(held.record.entries.items()) if e.binding_id == binding_id)


def nothing_pending(binding_id: binding_ids.BindingId) -> bool:
    """Whether the ledger can be read and holds no entry of the binding, so a retry has nothing to do or report."""
    try:
        held = ledger()
    except ValueError:
        return False
    if isinstance(held, id_property_records.RefusedRecord):
        return False
    return held is None or all(e.binding_id != binding_id for e in held.record.entries.values())


def set_ledger_entries(changed: Mapping[str, cleanup_ledgers.LedgerEntry], removed: Collection[str] = ()) -> None:
    """Change some of the ledger's entries, writing only those; a file with no ledger yet starts from an empty one.

    An empty update writes nothing. Raises as check_trackable does, and ValueError or TypeError, changing nothing, over
    an update that makes no ledger.
    """
    text = _trackable_text()
    if not changed and not removed:
        return
    stored = cleanup_ledgers.read_ledger(text)
    assert not isinstance(stored, id_property_records.RefusedRecord)  # _trackable_text refused it
    after = (cleanup_ledgers.Ledger({}) if stored is None else stored.record).updated(changed, removed)
    cleanup_ledgers.write_ledger_entries(text, after, changed.keys(), removed)


def check_trackable() -> None:
    """Raise unless the ledger can record work.

    RefusedRecordError over one that can't be read, and ValueError if the file has no binding index to hold it or more
    than one.
    """
    _trackable_text()


def _trackable_text() -> bpy.types.Text:
    """The index Text, holding a ledger that can be read or none yet; raises as check_trackable does."""
    text = _index_text()
    if text is None:
        raise ValueError("This file has no binding index to hold the pending-cleanup ledger")
    if isinstance(stored := cleanup_ledgers.read_ledger(text), id_property_records.RefusedRecord):
        raise id_property_records.RefusedRecordError(stored)
    return text


def _index_text() -> bpy.types.Text | None:
    """The file's only binding index Text, or None if it has none; ValueError if it has more."""
    texts = binding_records.index_texts()
    if len(texts) > 1:
        raise ValueError(f"This file has {len(texts)} binding indexes")
    return texts[0] if texts else None
