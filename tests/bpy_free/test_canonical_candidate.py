"""The canonical-candidate rule on its cases (source-access.md#canonical-candidate; COPY-03, COPY-09 to COPY-11).

Candidates are given by the destination each names (1 is the original's, 2 a copy's) and whether their
record and destination refer to each other; tests/blender/test_copies.py checks what Blender's copy
routes give it.
"""

from __future__ import annotations

import pytest

from proscenium.core.canonical_candidate import (
    UNREADABLE_INDEX_ENTRY,
    CandidateEvidence,
    CanonicalDecision,
    DecisionReason,
    decide,
)

ORIGINAL = CandidateEvidence(1, mutual=True)
FULL_COPY = CandidateEvidence(2, mutual=True)  # a full-copy scene's or an append's pair, which refer to each other
LINKED_COPY = CandidateEvidence(1, mutual=False)  # a linked-copy scene's record, naming the original destination
COLLECTION_COPY = CandidateEvidence(2, mutual=False)  # a tagged collection no record names
REMOVED = CandidateEvidence(None, mutual=False)  # a record whose destination was removed


@pytest.mark.parametrize(
    ("candidates", "entries", "expected"),
    [
        # Unique: one candidate and at most one index naming it, whatever the candidate's references.
        ([ORIGINAL], [1], CanonicalDecision(0, DecisionReason.UNIQUE)),
        ([ORIGINAL], [], CanonicalDecision(0, DecisionReason.UNIQUE)),
        ([REMOVED], [None], CanonicalDecision(0, DecisionReason.UNIQUE)),
        ([ORIGINAL], [UNREADABLE_INDEX_ENTRY], CanonicalDecision(0, DecisionReason.UNIQUE)),
        (
            [],
            [1],
            CanonicalDecision(None, DecisionReason.UNIQUE),
        ),  # a tagged collection's identity with no binding left
        # COPY-09: the index names the canonical candidate's destination, whatever the order found.
        ([ORIGINAL, FULL_COPY], [1], CanonicalDecision(0, DecisionReason.INDEXED)),
        ([FULL_COPY, ORIGINAL], [1], CanonicalDecision(1, DecisionReason.INDEXED)),
        ([ORIGINAL, LINKED_COPY], [1], CanonicalDecision(0, DecisionReason.INDEXED)),
        ([LINKED_COPY, ORIGINAL, COLLECTION_COPY], [1], CanonicalDecision(1, DecisionReason.INDEXED)),
        # COPY-10: no usable entry, so the one mutual candidate; two or none disable every candidate.
        ([ORIGINAL, LINKED_COPY], [], CanonicalDecision(0, DecisionReason.MUTUAL)),
        ([ORIGINAL, COLLECTION_COPY], [None], CanonicalDecision(0, DecisionReason.MUTUAL)),
        ([ORIGINAL, FULL_COPY], [], CanonicalDecision(None, DecisionReason.SEVERAL_MUTUAL)),
        ([LINKED_COPY, COLLECTION_COPY], [], CanonicalDecision(None, DecisionReason.NONE_MUTUAL)),
        # COPY-11: the rule can't decide.
        ([ORIGINAL], [1, 1], CanonicalDecision(None, DecisionReason.SEVERAL_INDEXES)),
        ([ORIGINAL, FULL_COPY], [1, UNREADABLE_INDEX_ENTRY], CanonicalDecision(None, DecisionReason.SEVERAL_INDEXES)),
        ([ORIGINAL, FULL_COPY], [UNREADABLE_INDEX_ENTRY], CanonicalDecision(None, DecisionReason.UNREADABLE_INDEX)),
        ([ORIGINAL, COLLECTION_COPY], [2], CanonicalDecision(None, DecisionReason.INDEX_DISAGREES)),
        ([ORIGINAL, FULL_COPY], [3], CanonicalDecision(None, DecisionReason.INDEX_DISAGREES)),
    ],
)
def test_rule(candidates: list[CandidateEvidence], entries: list[int | None], expected: CanonicalDecision) -> None:
    assert decide(candidates, entries) == expected
    assert decide(candidates, entries) == expected  # COPY-03: deterministic
