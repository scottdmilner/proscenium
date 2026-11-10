"""The canonical-candidate rule (source-access.md#canonical-candidate), on what Blender data says about each candidate.

A binding identity's candidates are the local collections holding a binding record for it whose target scene exists
(source-access.md#copied-bindings). The rule reads only which collection each binding index's entry names.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, override

if TYPE_CHECKING:
    from collections.abc import Sequence


class UnreadableIndexEntry:
    """The type of UNREADABLE_INDEX_ENTRY."""

    @override
    def __repr__(self) -> str:
        return "UNREADABLE_INDEX_ENTRY"


UNREADABLE_INDEX_ENTRY: Final = UnreadableIndexEntry()  # an index entry from a binding index that can't be read


class CanonicalCandidateReason(StrEnum):
    """Why the rule chose what it did."""

    UNIQUE = "unique"  # one candidate, and at most one index naming it: the identity is unique
    INDEXED = "indexed"  # the index names the canonical candidate's collection
    SEVERAL_INDEXES = "several indexes"  # more than one index names the identity
    UNREADABLE_INDEX = "unreadable index"  # an index that names it, or may, can't be read
    NOT_INDEXED = "not indexed"  # the index has no entry for the identity, or one naming no collection
    INDEX_DISAGREES = "index disagrees"  # the index names a collection that isn't one of the candidates


@dataclass(frozen=True, slots=True)
class CanonicalDecision:
    """The rule's decision on an identity's candidates, and why."""

    canonical: int | None  # the canonical candidate's position in the candidates, or None: all are disabled
    reason: CanonicalCandidateReason


def decide(candidates: Sequence[int], entries: Sequence[int | None | UnreadableIndexEntry]) -> CanonicalDecision:
    """The canonical candidate of one identity, as a position in candidates, or None if every one is disabled.

    candidates are the session_uids of the identity's candidates' collections. entries has one item per binding index
    in the file that names the identity, or might:
    - the session_uid of the collection its entry names, or None for an entry naming none;
    - UNREADABLE_INDEX_ENTRY for an index that can't be read.

    An identity with one candidate and at most one entry is unique whatever its entry says.
    """
    if len(candidates) <= 1 and len(entries) <= 1:
        return CanonicalDecision(0 if candidates else None, CanonicalCandidateReason.UNIQUE)
    if len(entries) > 1:
        return CanonicalDecision(None, CanonicalCandidateReason.SEVERAL_INDEXES)
    entry = entries[0] if entries else None
    if isinstance(entry, UnreadableIndexEntry):
        return CanonicalDecision(None, CanonicalCandidateReason.UNREADABLE_INDEX)
    if entry is None:
        return CanonicalDecision(None, CanonicalCandidateReason.NOT_INDEXED)
    if entry in candidates:
        return CanonicalDecision(candidates.index(entry), CanonicalCandidateReason.INDEXED)
    return CanonicalDecision(None, CanonicalCandidateReason.INDEX_DISAGREES)
