"""The pending-cleanup ledger: resources left to dispose of, and what a retry needs (lifecycle.md#pending-cleanup).

A versioned record on the binding index's Text (DECISIONS.md "Pending-cleanup tracking mechanism"), which no copy route
copies, so no copy can authorize disposing of a copy's content, and which removing a binding doesn't remove. It has one
entry per pending resource, keyed by a random ledger key, holding the contract's evidence: its binding, its entry key
and role in that binding's manifest, a pointer to its datablock, its originating operation, and its cleanup diagnostic.
An entry is written only when an operation fails to remove its resource: until then the operation holds what it would
remove, so one whose removals all succeed writes nothing.

- An entry's entry key isn't unique: a prepared replacement takes its published resource's key, and a retired resource
  keeps the key the new generation may reuse. Its ledger key is, and a cleanup diagnostic names it.
- The ledger's pointers are users of the datablocks they name, so a leftover is saved with the file and found after
  reopening. Removing a datablock clears its pointer, leaving an entry with nothing to dispose of.
- Recording or resolving work writes only the ledger, never a manifest, a generation, or a last attempt.
- One that can't be read is kept and authorizes no disposal: writers read it first and refuse.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

import bpy

from .. import results
from . import records
from .manifests import RepresentationRole
from .records import Loaded, RefusedRecord, Schema

if TYPE_CHECKING:
    from collections.abc import Collection

    from ..source_access import identifiers

LEDGER_KEY = "ledger"

_LEDGER_KEY = re.compile(r"[0-9a-f]{32}")


class OriginatingOperation(StrEnum):
    """The operation that left a resource pending."""

    SYNCHRONIZE = "synchronize"


def new_ledger_key() -> str:
    """A random ledger key: 128 bits as 32 hex digits, short enough for an ID-property key."""
    return secrets.token_hex(16)


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One pending resource."""

    binding_id: identifiers.BindingId  # the binding that owns it
    entry_key: str  # its key in that binding's manifest: the entry it was prepared as, or published as
    role: RepresentationRole  # a record stores the value
    datablock: bpy.types.ID | None  # None once it's removed: removing a datablock clears pointers to it
    operation: OriginatingOperation
    diagnostic: results.Diagnostic  # why its removal failed, naming its ledger key

    def __post_init__(self) -> None:
        if type(self.binding_id) is not str or type(self.entry_key) is not str:
            raise TypeError("an entry names its binding and its entry key")
        if not isinstance(self.datablock, bpy.types.ID | None):
            raise TypeError("an entry's datablock is not one")
        # Stored as plain values; ValueError for one outside its vocabulary.
        object.__setattr__(self, "role", RepresentationRole(self.role))
        object.__setattr__(self, "operation", OriginatingOperation(self.operation))
        if isinstance(self.diagnostic, Mapping):
            object.__setattr__(self, "diagnostic", results.Diagnostic(**self.diagnostic))
        if not isinstance(self.diagnostic, results.Diagnostic):
            raise TypeError("an entry has the cleanup diagnostic of its failed removal")


@dataclass(frozen=True)
class Ledger:
    """An immutable value: its entries are a read-only view of a dict nothing else holds."""

    entries: Mapping[str, LedgerEntry]  # ledger key -> its entry

    def __post_init__(self) -> None:
        # A stored ledger's entries are plain groups; build them.
        entries = {key: e if isinstance(e, LedgerEntry) else LedgerEntry(**e) for key, e in self.entries.items()}
        _check_keys(entries)
        object.__setattr__(self, "entries", MappingProxyType(entries))

    def updated(self, changed: Mapping[str, LedgerEntry], removed: Collection[str]) -> Ledger:
        """This ledger with changed's entries added or replaced and removed's deleted.

        The checks cost what changes; the result copies the entries. Raises ValueError or TypeError over an update that
        makes no ledger.
        """
        if not changed.keys().isdisjoint(removed):
            raise ValueError("an update both changes and removes an entry")
        if missing := set(removed) - self.entries.keys():
            raise ValueError(f"removes entries the ledger doesn't have: {sorted(missing)}")
        if not all(type(e) is LedgerEntry for e in changed.values()):
            raise TypeError("a changed entry is not a LedgerEntry")
        _check_keys(changed)
        entries = dict(self.entries)
        for key in removed:
            del entries[key]
        entries.update(changed)
        ledger = object.__new__(Ledger)  # checked above, so not again in __post_init__
        object.__setattr__(ledger, "entries", MappingProxyType(entries))
        return ledger


def _check_keys(entries: Mapping[str, LedgerEntry]) -> None:
    if bad := [key for key in entries if type(key) is not str or not _LEDGER_KEY.fullmatch(key)]:
        raise ValueError(f"ledger keys are 32 hex digits, not {sorted(map(repr, bad))}")


LEDGER = Schema("pending-cleanup ledger", version=1, record_type=Ledger)


def read_ledger(text: bpy.types.Text) -> Loaded[Ledger] | RefusedRecord | None:
    """The ledger on the binding index's Text, why it can't be read, or None if it has none."""
    return records.read(text, LEDGER_KEY, LEDGER)


def write_ledger_entries(
    text: bpy.types.Text, ledger: Ledger, changed: Collection[str], removed: Collection[str]
) -> Loaded[Ledger]:
    """Store ledger, writing only the entries under changed and removed; the ledger as reading it would give it.

    ledger differs from the stored one only in those entries (records.write_items). Raises RefusedRecordError, changing
    nothing, over a stored ledger that can't be read.
    """
    records.write_items(text, LEDGER_KEY, LEDGER, ledger, "entries", changed, removed)
    return Loaded(ledger, LEDGER.version)
