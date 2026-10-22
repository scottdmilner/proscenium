"""The canonical-candidate rule (source-access.md#canonical-candidate), on what Blender data says about each candidate.

A binding identity's candidates are its binding records, one per scene, and the destination collections
tagged with it that no record names (source-access.md#copied-bindings). The rule reads, for each, which
destination it names and whether its record and destination refer to each other, and, for the identity,
what each binding index in the file says about it. It returns the canonical candidate, or none.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final, override

if TYPE_CHECKING:
    from collections.abc import Sequence


class Unreadable:
    """The type of UNREADABLE."""

    @override
    def __repr__(self) -> str:
        return "UNREADABLE"


UNREADABLE: Final = Unreadable()  # an index entry from a binding index that can't be read


@dataclass(frozen=True, slots=True)
class Candidate:
    destination: int | None  # the session_uid of the collection its record names, or of the tagged collection
    mutual: bool  # its binding record names the destination, and the destination's tag points back at its scene


class Reason(StrEnum):
    """Why the rule chose what it did."""

    UNIQUE = "unique"  # one candidate, and at most one index naming it: the identity is unique
    INDEXED = "indexed"  # the index names the canonical candidate's destination
    MUTUAL = "mutual"  # no usable index entry, and one candidate whose record and destination refer to each other
    SEVERAL_INDEXES = "several indexes"  # more than one index names the identity
    UNREADABLE_INDEX = "unreadable index"  # an index that names it, or may, can't be read
    INDEX_DISAGREES = "index disagrees"  # the index names a destination whose record doesn't refer back
    SEVERAL_MUTUAL = "several mutual"  # no usable index entry, and two or more candidates refer both ways
    NONE_MUTUAL = "none mutual"  # no usable index entry, and no candidate refers both ways


@dataclass(frozen=True, slots=True)
class Decision:
    canonical: int | None  # the canonical candidate's position in the candidates, or None: all are disabled
    reason: Reason


def decide(candidates: Sequence[Candidate], entries: Sequence[int | None | Unreadable]) -> Decision:
    """The canonical candidate of one identity.

    entries has one item per binding index in the file that names the identity: the destination its entry
    names, None for an entry naming no destination, or UNREADABLE for an index that can't be read, which
    might name it. An identity with one candidate and at most one such index is unique, whatever its
    candidate's references, so a binding whose destination was removed stays enabled
    (lifecycle.md#removed-destination); otherwise the rule decides, or every candidate is disabled.
    """
    if len(candidates) <= 1 and len(entries) <= 1:
        return Decision(0 if candidates else None, Reason.UNIQUE)
    if len(entries) > 1:
        return Decision(None, Reason.SEVERAL_INDEXES)
    entry = entries[0] if entries else None
    if isinstance(entry, Unreadable):
        return Decision(None, Reason.UNREADABLE_INDEX)
    if entry is not None:
        named = [i for i, c in enumerate(candidates) if c.destination == entry and c.mutual]
        return Decision(named[0], Reason.INDEXED) if named else Decision(None, Reason.INDEX_DISAGREES)
    mutual = [i for i, c in enumerate(candidates) if c.mutual]
    if len(mutual) == 1:
        return Decision(mutual[0], Reason.MUTUAL)
    return Decision(None, Reason.SEVERAL_MUTUAL if mutual else Reason.NONE_MUTUAL)
