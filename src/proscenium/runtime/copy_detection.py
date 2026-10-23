"""Copied-binding detection (source-access.md#copied-bindings).

detect() reads the file's destination tags and binding indexes, and returns each binding identity's candidates with
the canonical-candidate rule's decision on them (proscenium.core.canonical_candidate). A candidate is one of the
identity's binding records, one per local scene, or a local collection tagged with the identity that no record names,
as a collection duplicated on its own is. report() describes an identity that isn't unique.

Detection never writes: whether a binding is disabled is derived from the records each time they are read, never
stored, so it survives save and reopen and no copy carries it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from ..core.canonical_candidate import (
    UNREADABLE_INDEX_ENTRY,
    CandidateEvidence,
    DecisionReason,
    UnreadableIndexEntry,
    decide,
)
from ..persistence import binding_records, records
from ..persistence.records import Loaded, RefusedRecord

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import bpy

    from ..core.binding_ids import BindingId
    from ..core.canonical_candidate import CanonicalDecision
    from ..persistence.binding_records import BindingConfig, DestinationTag
    from .state import Candidate

    Entry = int | None | UnreadableIndexEntry  # what one binding index says about an identity (decide)
    Index = Mapping[BindingId, int | None] | UnreadableIndexEntry  # by binding: its destination's session_uid


class TaggedCollection(NamedTuple):
    """A local collection with a destination tag."""

    collection: bpy.types.Collection
    tag: DestinationTag | None  # None if the tag can't be read, so it points at no binding


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


@dataclass(slots=True)
class IdentityCandidates:
    """One binding identity's candidates, its records and then its tagged copies, and the rule's decision on them."""

    records: list[Candidate]  # one per local scene, in the order found
    tagged_copies: list[bpy.types.Collection]  # tagged collections no record of the identity names
    evidence: list[CandidateEvidence]  # what the rule reads, one per candidate: the records', then the copies'
    entries: list[Entry]  # what each binding index naming the identity, or unreadable, says
    decision: CanonicalDecision  # its canonical position is a position in evidence

    def canonical_record(self) -> Candidate | None:
        """The canonical candidate, or None if every candidate is disabled. Only for an identity with records.

        The rule's position is always a record's: with records, it picks the only candidate or a mutual one, and a
        tagged copy is never mutual.
        """
        assert self.records
        return None if (position := self.decision.canonical) is None else self.records[position]

    def restored(self, destination: bpy.types.Collection) -> None:
        """The index now names destination, as the canonical candidate's write restored its entry."""
        self.entries = [destination.session_uid]
        self.decision = decide(self.evidence, self.entries)


@dataclass(frozen=True, slots=True)
class CopyDetection:
    """What detection found: every identity's candidates, and the tagged collections."""

    identities: dict[BindingId, IdentityCandidates]  # every identity with a record or a tagged collection
    tagged: frozenset[int]  # the session_uids of the local tagged collections (binding_records.tagged_uids)


def detect(records_by_id: Mapping[BindingId, Sequence[Candidate]]) -> CopyDetection:
    """Every identity's candidates and decision, from its binding records in the order found and the file's tags."""
    tagged = _read_tagged()
    indexes = _read_indexes()
    record_evidence = {
        binding_id: [_record_evidence(binding_id, candidate, tagged) for candidate in identity_records]
        for binding_id, identity_records in records_by_id.items()
    }
    copies = _tagged_copies(record_evidence, tagged)
    binding_ids = [*records_by_id, *(b for b in copies if b not in records_by_id)]
    identities = {
        binding_id: _identity(
            binding_id,
            list(records_by_id.get(binding_id, ())),
            record_evidence.get(binding_id, []),
            copies.get(binding_id, []),
            indexes,
        )
        for binding_id in binding_ids
    }
    return CopyDetection(identities, frozenset(tagged))


def report(binding_id: BindingId, identity: IdentityCandidates) -> CopiedBinding:
    """The identity's candidates by name, for reporting: names aren't identities, and may change."""
    canonical = identity.decision.canonical
    reports = [
        CandidateReport(c.scene.name, None if (d := _destination(c.config)) is None else d.name, position == canonical)
        for position, c in enumerate(identity.records)
    ]
    # The copies' positions follow the records', as their evidence does.
    reports += [
        CandidateReport(None, c.name, position == canonical)
        for position, c in enumerate(identity.tagged_copies, start=len(identity.records))
    ]
    return CopiedBinding(binding_id, identity.decision.reason, tuple(reports))


def refers_back(binding_id: BindingId, scene: bpy.types.Scene, config: BindingConfig) -> bool:
    """Whether config's destination is tagged with binding_id and points back at scene, read from the destination."""
    if config.destination is None:
        return False
    tag = records.read(config.destination, binding_records.TAG_KEY, binding_records.TAG)
    return _points_back(tag.record if isinstance(tag, Loaded) else None, binding_id, scene)


def _read_tagged() -> dict[int, TaggedCollection]:
    """Every local tagged collection, by session_uid."""
    return {
        collection.session_uid: TaggedCollection(collection, tag.record if isinstance(tag, Loaded) else None)
        for collection, tag in binding_records.read_tags()
    }


def _read_indexes() -> list[Index]:
    """Every binding index in the file, with its destinations by session_uid, or UNREADABLE_INDEX_ENTRY."""
    indexes: list[Index] = []
    for text in binding_records.index_texts():
        index = records.read(text, binding_records.INDEX_KEY, binding_records.INDEX)
        if not isinstance(index, Loaded):
            indexes.append(UNREADABLE_INDEX_ENTRY)
            continue
        destinations = index.record.destinations
        indexes.append({b: None if d is None else d.session_uid for b, d in destinations.items()})
    return indexes


def _record_evidence(
    binding_id: BindingId, candidate: Candidate, tagged: Mapping[int, TaggedCollection]
) -> CandidateEvidence:
    """What the rule reads about a binding record: the destination it names, and whether that tag points back."""
    config = candidate.config
    if isinstance(config, RefusedRecord):
        # A record that can't be read names no destination, but a collection whose tag points back at its scene is
        # its destination, not a copy: the binding is unreadable, not copied.
        destination = next((uid for uid, t in tagged.items() if _points_back(t.tag, binding_id, candidate.scene)), None)
        return CandidateEvidence(destination, mutual=False)
    if config.destination is None:
        return CandidateEvidence(None, mutual=False)
    uid = config.destination.session_uid
    tag = tagged[uid].tag if uid in tagged else None
    return CandidateEvidence(uid, mutual=_points_back(tag, binding_id, candidate.scene))


def _tagged_copies(
    record_evidence: Mapping[BindingId, Sequence[CandidateEvidence]], tagged: Mapping[int, TaggedCollection]
) -> dict[BindingId, list[bpy.types.Collection]]:
    """By binding identity, the tagged collections none of its records names: its tagged copies."""
    named = {
        (b, e.destination) for b, evidence in record_evidence.items() for e in evidence if e.destination is not None
    }
    copies: dict[BindingId, list[bpy.types.Collection]] = {}
    for uid, (collection, tag) in tagged.items():
        if tag is not None and (tag.binding_id, uid) not in named:
            copies.setdefault(tag.binding_id, []).append(collection)
    return copies


def _identity(
    binding_id: BindingId,
    identity_records: list[Candidate],
    record_evidence: list[CandidateEvidence],
    copies: list[bpy.types.Collection],
    indexes: Sequence[Index],
) -> IdentityCandidates:
    """The identity's candidates, the index entries naming it, and the rule's decision."""
    evidence = [*record_evidence, *(CandidateEvidence(c.session_uid, mutual=False) for c in copies)]
    entries: list[Entry] = [
        index if isinstance(index, UnreadableIndexEntry) else index[binding_id]
        for index in indexes
        if isinstance(index, UnreadableIndexEntry) or binding_id in index
    ]
    return IdentityCandidates(identity_records, copies, evidence, entries, decide(evidence, entries))


def _points_back(tag: DestinationTag | None, binding_id: BindingId, scene: bpy.types.Scene) -> bool:
    return tag is not None and tag.binding_id == binding_id and tag.scene == scene


def _destination(config: BindingConfig | RefusedRecord) -> bpy.types.Collection | None:
    return None if isinstance(config, RefusedRecord) else config.destination
