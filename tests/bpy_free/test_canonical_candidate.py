"""The canonical-candidate rule on its cases (source-access.md#canonical-candidate; COPY-03, COPY-09, COPY-11).

Candidates are given by their collections' session_uids (1 is the original's, 2 and 3 copies');
tests/blender/test_copies.py checks what Blender's copy routes give it.
"""

from __future__ import annotations

import pytest

from proscenium.binding.source_access.canonical_candidate import (
    UNREADABLE_INDEX_ENTRY,
    CanonicalCandidateReason,
    CanonicalDecision,
    UnreadableIndexEntry,
    decide,
)


@pytest.mark.parametrize(
    ("candidates", "entries", "expected"),
    [
        # Unique: one candidate and at most one index naming it, whatever its entry says.
        ([1], [1], CanonicalDecision(0, CanonicalCandidateReason.UNIQUE)),
        ([1], [], CanonicalDecision(0, CanonicalCandidateReason.UNIQUE)),
        ([1], [None], CanonicalDecision(0, CanonicalCandidateReason.UNIQUE)),
        ([1], [2], CanonicalDecision(0, CanonicalCandidateReason.UNIQUE)),
        ([1], [UNREADABLE_INDEX_ENTRY], CanonicalDecision(0, CanonicalCandidateReason.UNIQUE)),
        ([], [1], CanonicalDecision(None, CanonicalCandidateReason.UNIQUE)),  # an identity with no binding left
        # COPY-09: the index names the canonical candidate's collection, whatever the order found.
        ([1, 2], [1], CanonicalDecision(0, CanonicalCandidateReason.INDEXED)),
        ([2, 1], [1], CanonicalDecision(1, CanonicalCandidateReason.INDEXED)),
        ([2, 3, 1], [1], CanonicalDecision(2, CanonicalCandidateReason.INDEXED)),
        # COPY-11: the rule can't decide.
        ([1], [1, 1], CanonicalDecision(None, CanonicalCandidateReason.SEVERAL_INDEXES)),
        ([1, 2], [1, UNREADABLE_INDEX_ENTRY], CanonicalDecision(None, CanonicalCandidateReason.SEVERAL_INDEXES)),
        ([1, 2], [UNREADABLE_INDEX_ENTRY], CanonicalDecision(None, CanonicalCandidateReason.UNREADABLE_INDEX)),
        ([1, 2], [], CanonicalDecision(None, CanonicalCandidateReason.NOT_INDEXED)),
        ([1, 2], [None], CanonicalDecision(None, CanonicalCandidateReason.NOT_INDEXED)),
        ([1, 2], [3], CanonicalDecision(None, CanonicalCandidateReason.INDEX_DISAGREES)),
    ],
)
def test_rule(
    candidates: list[int], entries: list[int | None | UnreadableIndexEntry], expected: CanonicalDecision
) -> None:
    assert decide(candidates, entries) == expected
    assert decide(candidates, entries) == expected  # COPY-03: deterministic
