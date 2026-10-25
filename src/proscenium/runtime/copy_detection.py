"""Copied-binding detection (source-access.md#copied-bindings).

identities() finds each binding identity's candidates in the records the bindings' state holds, and the
canonical-candidate rule's decision on them (proscenium.core.canonical_candidate). A candidate is one of the identity's
binding records, one per local scene, or a local collection tagged with the identity that no record names, as a
collection duplicated on its own is. report() describes an identity that isn't unique.

Detection reads only the state's records, and never writes: whether a binding is disabled is derived from the records
each time they are read, never stored, so it survives save and reopen and no copy carries it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..core.canonical_candidate import (
    UNREADABLE_INDEX_ENTRY,
    CandidateEvidence,
    DecisionReason,
    UnreadableIndexEntry,
    decide,
)
from ..persistence.binding_records import BindingIndex, DestinationTag
from ..persistence.records import RefusedRecord

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import bpy

    from ..core.binding_ids import BindingId
    from ..core.canonical_candidate import CanonicalDecision
    from .state import BindingRecord, DestinationRecords, State

    Entry = int | None | UnreadableIndexEntry  # what one binding index says about an identity (decide)
    Index = Mapping[BindingId, int | None] | UnreadableIndexEntry  # by binding: its destination's session_uid


@dataclass(frozen=True, slots=True)
class CandidateReport:
    """One candidate of a copied binding, by scene and destination name, and whether it is canonical."""

    scene: str | None  # the scene holding its binding record; None for a tagged collection no record names
    destination: str | None  # the collection its record names, or the tagged collection; None once removed
    canonical: bool


@dataclass(frozen=True, slots=True)
class CopiedBinding:
    """A binding identity that isn't unique: its candidates, and why the rule chose its canonical one, or none."""

    binding_id: BindingId
    reason: DecisionReason
    candidates: tuple[CandidateReport, ...]

    @property
    def disabled(self) -> bool:
        """Whether every candidate is disabled pending repair: the rule couldn't decide."""
        return not any(c.canonical for c in self.candidates)


@dataclass(frozen=True, slots=True)
class Candidate:
    """One candidate of a binding identity: one of its binding records, or a tagged collection none of them names."""

    record: BindingRecord | None  # None for a tagged copy
    collection: bpy.types.Collection | None  # the collection its readable record names, or the tagged copy
    evidence: CandidateEvidence  # what the rule reads about it


@dataclass(frozen=True, slots=True)
class IdentityCandidates:
    """One binding identity's candidates, and the rule's decision on them."""

    candidates: tuple[Candidate, ...]  # its binding records, in the order found, then its tagged copies
    index_entries: tuple[Entry, ...]  # what each binding index naming the identity, or unreadable, says
    decision: CanonicalDecision  # its canonical position is a position in candidates

    @property
    def records(self) -> tuple[BindingRecord, ...]:
        """The identity's binding records; none if it has only tagged copies, which aren't a binding."""
        return tuple(c.record for c in self.candidates if c.record is not None)

    def canonical_record(self) -> BindingRecord | None:
        """The canonical candidate's record, or None if every candidate is disabled. Only for an identity with records.

        The rule's position is always a record's: with records, it picks the only candidate or a mutual one, and a
        tagged copy is never mutual.
        """
        assert self.records
        if (position := self.decision.canonical) is None:
            return None
        record = self.candidates[position].record
        assert record is not None
        return record


def identities(current: State) -> dict[BindingId, IdentityCandidates]:
    """Every identity with a binding record or a tagged collection, records' first, its candidates and decision."""
    by_identity: dict[BindingId, list[BindingRecord]] = {}
    for held in current.scenes.values():
        for record in held.records():
            by_identity.setdefault(record.binding_id, []).append(record)
    tagged_with = _tagged_with(current)
    indexes = _indexes(current)
    binding_ids = [*by_identity, *(b for b in tagged_with if b not in by_identity)]
    return {b: _identity(current, b, by_identity.get(b, ()), tagged_with.get(b, []), indexes) for b in binding_ids}


def identity(current: State, binding_id: BindingId, records: Sequence[BindingRecord]) -> IdentityCandidates:
    """One identity's candidates and decision, given its binding records, after a write changed what the rule reads."""
    tagged = [d for d in current.destinations.values() if _tagged_binding(d) == binding_id]
    return _identity(current, binding_id, records, tagged, _indexes(current))


def report(binding_id: BindingId, identity: IdentityCandidates) -> CopiedBinding:
    """The identity's candidates by name, for reporting: names aren't identities, and may change."""
    canonical = identity.decision.canonical
    reports = [
        CandidateReport(
            None if c.record is None else c.record.scene.name,
            None if c.collection is None else c.collection.name,
            position == canonical,
        )
        for position, c in enumerate(identity.candidates)
    ]
    return CopiedBinding(binding_id, identity.decision.reason, tuple(reports))


def refers_back(current: State, binding_id: BindingId, record: BindingRecord) -> bool:
    """Whether the record's destination is tagged with binding_id and points back at the record's scene."""
    if isinstance(record.config, RefusedRecord) or record.config.destination is None:
        return False
    destination = current.destinations.get(record.config.destination.session_uid)
    return destination is not None and _points_back(destination.tag, binding_id, record.scene)


def _identity(
    current: State,
    binding_id: BindingId,
    records: Sequence[BindingRecord],
    tagged: Sequence[DestinationRecords],
    indexes: Sequence[Index],
) -> IdentityCandidates:
    """The identity's candidates, index entries, and decision, from its records, tagged collections, and the indexes."""
    candidates = [_record_candidate(current, binding_id, r) for r in records]
    named = {c.evidence.destination for c in candidates}
    candidates += [
        Candidate(None, d.collection, CandidateEvidence(d.collection.session_uid, mutual=False))
        for d in tagged
        if d.collection.session_uid not in named
    ]
    entries = tuple(
        index if isinstance(index, UnreadableIndexEntry) else index[binding_id]
        for index in indexes
        if isinstance(index, UnreadableIndexEntry) or binding_id in index
    )
    return IdentityCandidates(tuple(candidates), entries, decide([c.evidence for c in candidates], entries))


def _record_candidate(current: State, binding_id: BindingId, record: BindingRecord) -> Candidate:
    """A binding record as a candidate: the destination it names, and whether that destination's tag points back."""
    config = record.config
    if isinstance(config, RefusedRecord):
        # A record that can't be read names no destination, but a collection whose tag points back at its scene is
        # its destination, not a copy: the binding is unreadable, not copied.
        uid = next(
            (uid for uid, d in current.destinations.items() if _points_back(d.tag, binding_id, record.scene)), None
        )
        return Candidate(record, None, CandidateEvidence(uid, mutual=False))
    if config.destination is None:
        return Candidate(record, None, CandidateEvidence(None, mutual=False))
    uid = config.destination.session_uid
    destination = current.destinations.get(uid)
    mutual = destination is not None and _points_back(destination.tag, binding_id, record.scene)
    return Candidate(record, config.destination, CandidateEvidence(uid, mutual=mutual))


def _tagged_with(current: State) -> dict[BindingId, list[DestinationRecords]]:
    """By binding identity, the collections tagged with it, in the order found."""
    tagged: dict[BindingId, list[DestinationRecords]] = {}
    for destination in current.destinations.values():
        if (binding_id := _tagged_binding(destination)) is not None:
            tagged.setdefault(binding_id, []).append(destination)
    return tagged


def _indexes(current: State) -> list[Index]:
    """Every binding index, with its destinations by session_uid, or UNREADABLE_INDEX_ENTRY."""
    return [
        {b: None if d is None else d.session_uid for b, d in index.destinations.items()}
        if isinstance(index, BindingIndex)
        else UNREADABLE_INDEX_ENTRY
        for index in (held.index for held in current.indexes)
    ]


def _tagged_binding(destination: DestinationRecords) -> BindingId | None:
    return destination.tag.binding_id if isinstance(destination.tag, DestinationTag) else None


def _points_back(tag: DestinationTag | RefusedRecord | None, binding_id: BindingId, scene: bpy.types.Scene) -> bool:
    return isinstance(tag, DestinationTag) and tag.binding_id == binding_id and tag.scene == scene
