"""The canonical-candidate rule on its cases (source-access.md#canonical-candidate; COPY-03, COPY-09 to COPY-11).

Candidates are given by the destination each names (1 is the original's, 2 a copy's) and whether their
record and destination refer to each other; tests/blender/test_copies.py checks what Blender's copy
routes give it.
"""

from __future__ import annotations

import pytest

from proscenium.core.copies import UNREADABLE, Candidate, Decision, Reason, decide

ORIGINAL = Candidate(1, mutual=True)
FULL_COPY = Candidate(2, mutual=True)  # a full-copy scene's or an append's pair, which refer to each other
LINKED_COPY = Candidate(1, mutual=False)  # a linked-copy scene's record, naming the original destination
COLLECTION_COPY = Candidate(2, mutual=False)  # a tagged collection no record names
REMOVED = Candidate(None, mutual=False)  # a record whose destination was removed


@pytest.mark.parametrize(
    ("candidates", "entries", "expected"),
    [
        # Unique: one candidate and at most one index naming it, whatever the candidate's references.
        ([ORIGINAL], [1], Decision(0, Reason.UNIQUE)),
        ([ORIGINAL], [], Decision(0, Reason.UNIQUE)),
        ([REMOVED], [None], Decision(0, Reason.UNIQUE)),
        ([ORIGINAL], [UNREADABLE], Decision(0, Reason.UNIQUE)),
        ([], [1], Decision(None, Reason.UNIQUE)),  # a tagged collection's identity with no binding left
        # COPY-09: the index names the canonical candidate's destination, whatever the order found.
        ([ORIGINAL, FULL_COPY], [1], Decision(0, Reason.INDEXED)),
        ([FULL_COPY, ORIGINAL], [1], Decision(1, Reason.INDEXED)),
        ([ORIGINAL, LINKED_COPY], [1], Decision(0, Reason.INDEXED)),
        ([LINKED_COPY, ORIGINAL, COLLECTION_COPY], [1], Decision(1, Reason.INDEXED)),
        # COPY-10: no usable entry, so the one mutual candidate; two or none disable every candidate.
        ([ORIGINAL, LINKED_COPY], [], Decision(0, Reason.MUTUAL)),
        ([ORIGINAL, COLLECTION_COPY], [None], Decision(0, Reason.MUTUAL)),
        ([ORIGINAL, FULL_COPY], [], Decision(None, Reason.SEVERAL_MUTUAL)),
        ([LINKED_COPY, COLLECTION_COPY], [], Decision(None, Reason.NONE_MUTUAL)),
        # COPY-11: the rule can't decide.
        ([ORIGINAL], [1, 1], Decision(None, Reason.SEVERAL_INDEXES)),
        ([ORIGINAL, FULL_COPY], [1, UNREADABLE], Decision(None, Reason.SEVERAL_INDEXES)),
        ([ORIGINAL, FULL_COPY], [UNREADABLE], Decision(None, Reason.UNREADABLE_INDEX)),
        ([ORIGINAL, COLLECTION_COPY], [2], Decision(None, Reason.INDEX_DISAGREES)),
        ([ORIGINAL, FULL_COPY], [3], Decision(None, Reason.INDEX_DISAGREES)),
    ],
)
def test_rule(candidates: list[Candidate], entries: list[int | None], expected: Decision) -> None:
    assert decide(candidates, entries) == expected
    assert decide(candidates, entries) == expected  # COPY-03: deterministic
