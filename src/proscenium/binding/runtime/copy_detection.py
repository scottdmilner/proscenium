"""Copied-binding detection (source-access.md#copied-bindings).

identities() finds each binding identity's candidates in the records the bindings' state holds, and the
canonical-candidate rule's decision on them (proscenium.binding.source_access.canonical_candidate). A candidate is a
local collection's binding record for the identity, one that can't be read or one whose target scene exists.
report() describes an identity that isn't unique.

Detection reads only the state's records, and never writes: whether a binding is disabled is derived from the records
each time they are read, never stored, so it survives save and reopen and no copy carries it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..persistence import configs
from ..source_access import canonical_candidate

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ..source_access import identifiers
    from .state import BindingRecord, State

    # What one binding index says about an identity (decide).
    Entry = int | None | canonical_candidate.UnreadableIndexEntry
    # By binding: its destination's session_uid.
    Index = Mapping[identifiers.BindingId, int | None] | canonical_candidate.UnreadableIndexEntry


@dataclass(frozen=True, slots=True)
class CandidateReport:
    """One candidate of a copied binding, by scene and destination name, and whether it is canonical."""

    scene: str | None  # the target scene its record names; None for a record that can't be read
    destination: str  # the collection holding its record
    canonical: bool


@dataclass(frozen=True, slots=True)
class CopiedBinding:
    """A binding identity that isn't unique: its candidates, and why the rule chose its canonical one, or none."""

    binding_id: identifiers.BindingId
    reason: canonical_candidate.DecisionReason
    candidates: tuple[CandidateReport, ...]

    @property
    def disabled(self) -> bool:
        """Whether every candidate is disabled pending repair: the rule couldn't decide."""
        return not any(c.canonical for c in self.candidates)


@dataclass(frozen=True, slots=True)
class IdentityCandidates:
    """One binding identity's candidates, and the rule's decision on them."""

    candidates: tuple[BindingRecord, ...]  # its binding records that are candidates, in the order found
    index_entries: tuple[Entry, ...]  # what each binding index naming the identity, or unreadable, says
    decision: canonical_candidate.CanonicalDecision  # its canonical position is a position in candidates

    def canonical_record(self) -> BindingRecord | None:
        """The canonical candidate's record, or None if every candidate is disabled."""
        position = self.decision.canonical
        return None if position is None else self.candidates[position]


def identities(current: State) -> dict[identifiers.BindingId, IdentityCandidates]:
    """Every identity with a candidate, in the order found, its candidates and decision."""
    by_identity: dict[identifiers.BindingId, list[BindingRecord]] = {}
    for held in current.destinations.values():
        for record in held.records_found():
            if record.candidate:
                by_identity.setdefault(record.binding_id, []).append(record)
    indexes = _indexes(current)
    return {b: _identity(b, found, indexes) for b, found in by_identity.items()}


def identity(
    current: State, binding_id: identifiers.BindingId, candidates: Sequence[BindingRecord]
) -> IdentityCandidates:
    """One identity's candidates and decision, after a write changed what the rule reads."""
    return _identity(binding_id, candidates, _indexes(current))


def report(binding_id: identifiers.BindingId, identity: IdentityCandidates) -> CopiedBinding:
    """The identity's candidates by name, for reporting: names aren't identities, and may change."""
    canonical = identity.decision.canonical
    reports = [
        CandidateReport(None if r.scene is None else r.scene.name, r.collection.name, position == canonical)
        for position, r in enumerate(identity.candidates)
    ]
    return CopiedBinding(binding_id, identity.decision.reason, tuple(reports))


def _identity(
    binding_id: identifiers.BindingId, candidates: Sequence[BindingRecord], indexes: Sequence[Index]
) -> IdentityCandidates:
    """The identity's candidates, index entries, and decision."""
    entries = tuple(
        index if isinstance(index, canonical_candidate.UnreadableIndexEntry) else index[binding_id]
        for index in indexes
        if isinstance(index, canonical_candidate.UnreadableIndexEntry) or binding_id in index
    )
    uids = [r.collection.session_uid for r in candidates]
    return IdentityCandidates(tuple(candidates), entries, canonical_candidate.decide(uids, entries))


def _indexes(current: State) -> list[Index]:
    """Every binding index, with its destinations by session_uid, or UNREADABLE_INDEX_ENTRY."""
    return [
        {b: None if d is None else d.session_uid for b, d in index.destinations.items()}
        if isinstance(index, configs.BindingIndex)
        else canonical_candidate.UNREADABLE_INDEX_ENTRY
        for index in (held.index for held in current.indexes)
    ]
