"""Copied-binding detection (source-access.md#copied-bindings): each identity's candidates, and the rule's decision.

A binding identity's candidates are its binding records, one per local scene, then the local collections
tagged with it that no record of it names, as a collection duplicated on its own is. The rule
(proscenium.core.canonical_candidate) reads which destination each names, whether its record and destination refer to
each other, and what each binding index in the file says about the identity. Whether a binding is
disabled is derived from the records like this whenever they are read, never stored, so it survives
save and reopen and no copy carries it. Reading writes nothing.
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
from ..persistence import binding_records, records
from ..persistence.records import Loaded, RefusedRecord

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import bpy

    from ..core.canonical_candidate import CanonicalDecision
    from ..persistence.binding_records import BindingConfig, DestinationTag

    Entry = int | None | UnreadableIndexEntry
    Tags = Mapping[int, tuple[bpy.types.Collection, Loaded[DestinationTag] | RefusedRecord]]


@dataclass(frozen=True, slots=True)
class CandidateReport:
    scene: str | None  # the scene holding its binding record; None for a tagged collection no record names
    destination: str | None  # the collection its record names, or the tagged collection; None once removed
    canonical: bool


@dataclass(frozen=True, slots=True)
class CopiedBinding:
    """A binding identity that isn't unique: its candidates, and why the rule chose its canonical one, or none."""

    binding_id: str
    reason: DecisionReason
    candidates: tuple[CandidateReport, ...]

    @property
    def disabled(self) -> bool:
        """Whether every candidate is disabled pending repair: the rule couldn't decide."""
        return not any(c.canonical for c in self.candidates)


@dataclass(slots=True)
class IdentityCandidates:
    """One binding identity's candidates, as the rule reads them, and its decision."""

    tagged_copies: list[bpy.types.Collection]  # tagged collections no record of the identity names, after its records
    candidates: list[CandidateEvidence]  # its records' in the order given, then its copies'
    entries: list[Entry]  # what each binding index naming it, or unreadable, says
    decision: CanonicalDecision

    def restored(self, destination: bpy.types.Collection) -> None:
        """The index now names destination, as the canonical candidate's write restored its entry."""
        self.entries = [destination.session_uid]
        self.decision = decide(self.candidates, self.entries)


@dataclass(frozen=True, slots=True)
class CopyDetection:
    identities: dict[
        str, IdentityCandidates
    ]  # by binding identifier, every identity with a record or a tagged collection
    tagged: frozenset[int]  # the session_uids of the local tagged collections (binding_records.tagged_uids)


def detect(
    records_by_id: Mapping[str, Sequence[tuple[bpy.types.Scene, BindingConfig | RefusedRecord]]],
) -> CopyDetection:
    """Every identity's candidates and decision, given each identity's binding records in the order found."""
    tags: Tags = {collection.session_uid: (collection, tag) for collection, tag in binding_records.tagged_collections()}
    indexes: list[Mapping[str, bpy.types.Collection | None] | UnreadableIndexEntry] = []
    for text in binding_records.index_texts():
        index = records.read(text, binding_records.INDEX_KEY, binding_records.INDEX)
        indexes.append(index.record.destinations if isinstance(index, Loaded) else UNREADABLE_INDEX_ENTRY)
    # A record that can't be read names no destination it can be checked against, but a collection whose tag
    # points back at its scene is its destination, not a copy: the binding is unreadable, not copied.
    named = {
        (binding_id, uid)
        for binding_id, found in records_by_id.items()
        for scene, config in found
        if (uid := _named(config, binding_id, scene, tags)) is not None
    }
    copies: dict[str, list[bpy.types.Collection]] = {}
    for uid, (collection, tag) in tags.items():
        if isinstance(tag, Loaded) and (tag.record.binding_id, uid) not in named:
            copies.setdefault(tag.record.binding_id, []).append(collection)
    identities = {}
    for binding_id in [*records_by_id, *(b for b in copies if b not in records_by_id)]:
        found = records_by_id.get(binding_id, ())
        candidates = [
            CandidateEvidence(_named(config, binding_id, scene, tags), _refers_back(binding_id, scene, config, tags))
            for scene, config in found
        ]
        candidates += [CandidateEvidence(c.session_uid, mutual=False) for c in copies.get(binding_id, ())]
        entries = [
            _entry(index, binding_id)
            for index in indexes
            if isinstance(index, UnreadableIndexEntry) or binding_id in index
        ]
        identities[binding_id] = IdentityCandidates(
            copies.get(binding_id, []), candidates, entries, decide(candidates, entries)
        )
    return CopyDetection(identities, frozenset(tags))


def report(
    binding_id: str,
    identity: IdentityCandidates,
    found: Sequence[tuple[bpy.types.Scene, BindingConfig | RefusedRecord]],
) -> CopiedBinding:
    """The identity's candidates by name, for reporting: names aren't identities, and may change."""
    canonical = identity.decision.canonical
    reports = [
        CandidateReport(scene.name, None if (d := _destination(config)) is None else d.name, i == canonical)
        for i, (scene, config) in enumerate(found)
    ]
    reports += [
        CandidateReport(None, c.name, len(found) + i == canonical) for i, c in enumerate(identity.tagged_copies)
    ]
    return CopiedBinding(binding_id, identity.decision.reason, tuple(reports))


def refers_back(binding_id: str, scene: bpy.types.Scene, config: BindingConfig) -> bool:
    """Whether config's destination is tagged with binding_id and points back at scene."""
    destination = config.destination
    tag = None if destination is None else records.read(destination, binding_records.TAG_KEY, binding_records.TAG)
    return _points_back(tag, binding_id, scene)


def _refers_back(binding_id: str, scene: bpy.types.Scene, config: BindingConfig | RefusedRecord, tags: Tags) -> bool:
    destination = _destination(config)
    found = None if destination is None else tags.get(destination.session_uid)
    return found is not None and _points_back(found[1], binding_id, scene)


def _points_back(tag: Loaded[DestinationTag] | RefusedRecord | None, binding_id: str, scene: bpy.types.Scene) -> bool:
    return isinstance(tag, Loaded) and tag.record.binding_id == binding_id and tag.record.scene == scene


def _destination(config: BindingConfig | RefusedRecord) -> bpy.types.Collection | None:
    return None if isinstance(config, RefusedRecord) else config.destination


def _named(config: BindingConfig | RefusedRecord, binding_id: str, scene: bpy.types.Scene, tags: Tags) -> int | None:
    """The session_uid of the destination a record names: for one that can't be read, the collection whose tag
    points back at its scene."""
    if isinstance(config, RefusedRecord):
        return next((uid for uid, (_, tag) in tags.items() if _points_back(tag, binding_id, scene)), None)
    return None if config.destination is None else config.destination.session_uid


def _entry(index: Mapping[str, bpy.types.Collection | None] | UnreadableIndexEntry, binding_id: str) -> Entry:
    if isinstance(index, UnreadableIndexEntry):
        return index
    return None if (destination := index[binding_id]) is None else destination.session_uid
