"""Copied-binding detection (source-access.md#copied-bindings), from the records as they are when asked.

A binding identity's candidates are the local collections' binding records for it that can't be read or whose target
scene exists (BindingRecord). candidates_for_binding() finds one identity's candidates, and candidates_by_binding()
every identity's, with the canonical-candidate rule's decision (proscenium.binding.source_access.canonical_candidate).
copied_binding_report() describes an identity that isn't unique.

Detection reads the records each time and never writes, so whether a binding is disabled is never stored: it
survives save and reopen, and no copy carries it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy

from ..persistence import binding_records, id_property_records
from ..persistence.id_property_records import LoadedRecord, RefusedRecord
from ..source_access import canonical_candidate

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ..source_access import BindingId

    # What one binding index says about an identity (decide).
    Entry = int | None | canonical_candidate.UnreadableIndexEntry
    # By binding: its destination's session_uid.
    Index = Mapping[BindingId, int | None] | canonical_candidate.UnreadableIndexEntry

type HeldConfig = binding_records.BindingConfig | RefusedRecord  # a configuration, or why it can't be read


@dataclass(frozen=True, slots=True)
class BindingRecord:
    """One collection's binding record for a binding identity, as read."""

    collection: bpy.types.Collection  # the binding's destination
    binding_id: BindingId
    config: HeldConfig

    @property
    def scene(self) -> bpy.types.Scene | None:
        """The target scene a readable configuration names; None for one that can't be read, or a removed scene."""
        return None if isinstance(self.config, RefusedRecord) else self.config.scene

    @property
    def candidate(self) -> bool:
        """Whether it's a candidate of its identity: unreadable, or naming a target scene that exists."""
        return isinstance(self.config, RefusedRecord) or self.config.scene is not None


@dataclass(frozen=True, slots=True)
class CandidateReport:
    """One candidate of a copied binding, by scene and destination name, and whether it is canonical."""

    scene_name: str | None  # the target scene its record names; None for a record that can't be read
    destination_name: str  # the collection holding its record
    is_canonical: bool


@dataclass(frozen=True, slots=True)
class CopiedBinding:
    """A binding identity that isn't unique: its candidates, and why the rule chose its canonical one, or none."""

    binding_id: BindingId
    reason: canonical_candidate.CanonicalCandidateReason
    candidates: tuple[CandidateReport, ...]

    @property
    def disabled(self) -> bool:
        """Whether every candidate is disabled pending repair: the rule couldn't decide."""
        return not any(c.is_canonical for c in self.candidates)


@dataclass(frozen=True, slots=True)
class IdentityCandidates:
    """One binding identity's candidates, and the rule's decision on them."""

    candidates: tuple[BindingRecord, ...]  # in the order found
    index_entries: tuple[Entry, ...]  # what each binding index naming the identity, or unreadable, says
    decision: canonical_candidate.CanonicalDecision  # its canonical position is a position in candidates

    def canonical_record(self) -> BindingRecord | None:
        """The canonical candidate's record, or None if every candidate is disabled."""
        position = self.decision.canonical_candidate_index
        return None if position is None else self.candidates[position]


def candidates_for_binding(binding_id: BindingId) -> IdentityCandidates | None:
    """One identity's candidates and decision, or None if it has none: reads only its own records and the index."""
    key = binding_records.config_key(binding_id)
    found = []
    for collection in bpy.data.collections:
        if collection.library is None and id_property_records.has(collection, key):
            result = id_property_records.read(collection, key, binding_records.CONFIG)
            assert result is not None  # has() found it
            found.append(_record(collection, binding_id, result))
    candidates = [r for r in found if r.candidate]
    return _identity(binding_id, candidates, _indexes()) if candidates else None


def candidates_by_binding() -> dict[BindingId, IdentityCandidates]:
    """Every identity with a candidate, in the order found, with its candidates and decision."""
    by_identity: dict[BindingId, list[BindingRecord]] = {}
    for collection, binding_id, result in binding_records.read_configs():
        record = _record(collection, binding_id, result)
        if record.candidate:
            by_identity.setdefault(binding_id, []).append(record)
    indexes = _indexes()
    return {b: _identity(b, found, indexes) for b, found in by_identity.items()}


def copied_binding_report(binding_id: BindingId, identity: IdentityCandidates) -> CopiedBinding:
    """The identity's candidates by name, for reporting: names aren't identities, and may change."""
    canonical = identity.decision.canonical_candidate_index
    reports = [
        CandidateReport(None if r.scene is None else r.scene.name, r.collection.name, position == canonical)
        for position, r in enumerate(identity.candidates)
    ]
    return CopiedBinding(binding_id, identity.decision.reason, tuple(reports))


def _record(
    collection: bpy.types.Collection,
    binding_id: BindingId,
    result: LoadedRecord[binding_records.BindingConfig] | RefusedRecord,
) -> BindingRecord:
    return BindingRecord(collection, binding_id, result if isinstance(result, RefusedRecord) else result.record)


def _identity(
    binding_id: BindingId, candidates: Sequence[BindingRecord], indexes: Sequence[Index]
) -> IdentityCandidates:
    """The identity's candidates, index entries, and decision."""
    entries = tuple(
        index if isinstance(index, canonical_candidate.UnreadableIndexEntry) else index[binding_id]
        for index in indexes
        if isinstance(index, canonical_candidate.UnreadableIndexEntry) or binding_id in index
    )
    uids = [r.collection.session_uid for r in candidates]
    return IdentityCandidates(tuple(candidates), entries, canonical_candidate.decide(uids, entries))


def _indexes() -> list[Index]:
    """Every binding index, with its destinations by session_uid, or UNREADABLE_INDEX_ENTRY."""
    found: list[Index] = []
    for text in binding_records.index_texts():
        index = binding_records.read_index(text)
        if isinstance(index, LoadedRecord):
            found.append({b: None if d is None else d.session_uid for b, d in index.record.destinations.items()})
        else:
            found.append(canonical_candidate.UNREADABLE_INDEX_ENTRY)
    return found
