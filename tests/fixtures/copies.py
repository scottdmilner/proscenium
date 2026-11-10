"""F-OWNERSHIP-AMBIGUITY: copied bindings, and the binding indexes the canonical-candidate rule reads.

Copied bindings on each copy route, and binding indexes lost, cleared, duplicated, disagreeing, or unreadable
(source-access.md#copied-bindings, source-access.md#canonical-candidate).

The routes are Blender operations, and the generator runs without bpy, so it gives a binding's source and,
for each route, the outcome the canonical-candidate rule gives what that route leaves, derived from the
rule and the route (D1 in docs/plans/M03-bindings.md), never from running it; tests/support/copies.py
runs the routes, on a binding "Shot" on the scene "Scene" whose destination holds what its synchronization of
Scene.TRANSACTION published: a placeholder per drawn gprim (fixtures.transaction). Candidates are counted as the
rule counts them: local collections holding a binding record whose target scene exists.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from proscenium.binding.source_access.canonical_candidate import CanonicalCandidateReason

from .scenes import Scene, copy_scene

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@dataclass(frozen=True)
class CanonicalCandidateOutcome:
    candidates: int  # the identity's candidates after the route
    canonical: bool  # whether the original stays canonical; False: every candidate is disabled
    reason: CanonicalCandidateReason


@dataclass(frozen=True)
class BindingCopyCase:
    outcome: CanonicalCandidateOutcome
    # After save and reopen, where it differs from after synchronizing.
    reopened: CanonicalCandidateOutcome | None = None
    index_untouched: bool = True  # the file keeps one index, whose entry names the original destination


INDEXED = CanonicalCandidateOutcome(2, canonical=True, reason=CanonicalCandidateReason.INDEXED)
UNIQUE = CanonicalCandidateOutcome(1, canonical=True, reason=CanonicalCandidateReason.UNIQUE)

ROUTES: dict[str, BindingCopyCase] = {
    # Copy routes: two collections hold the binding's records, and the index names the original.
    "collection-copy": BindingCopyCase(INDEXED),  # Collection.copy(): its records name the original's scene
    "deep-collection-copy": BindingCopyCase(INDEXED),  # Outliner > Duplicate Collection's inferred state (D1), by hand
    "full-copy-scene": BindingCopyCase(INDEXED),  # a second scene, and a destination whose records name it
    "append": BindingCopyCase(INDEXED),  # the destination appended from a copy of the file brings its scene
    "record-copy": BindingCopyCase(INDEXED),  # records assigned by script to another collection
    # A linked-copy scene shares the destination, so it adds no candidate.
    "linked-copy-scene": BindingCopyCase(UNIQUE),
    # The index lost, cleared, or disagreeing: nothing decides between two candidates, and one is unique.
    "index-lost": BindingCopyCase(
        CanonicalCandidateOutcome(2, canonical=False, reason=CanonicalCandidateReason.NOT_INDEXED),
        index_untouched=False,
    ),
    "index-lost-collection-copy": BindingCopyCase(
        CanonicalCandidateOutcome(2, canonical=False, reason=CanonicalCandidateReason.NOT_INDEXED),
        index_untouched=False,
    ),
    "index-lost-linked-copy": BindingCopyCase(UNIQUE, index_untouched=False),  # its synchronization restores the entry
    "entry-cleared": BindingCopyCase(UNIQUE, index_untouched=False),  # its synchronization replaces the entry
    "index-disagrees": BindingCopyCase(
        CanonicalCandidateOutcome(2, canonical=False, reason=CanonicalCandidateReason.INDEX_DISAGREES),
        index_untouched=False,
    ),
    "unreadable-index": BindingCopyCase(
        CanonicalCandidateOutcome(2, canonical=False, reason=CanonicalCandidateReason.UNREADABLE_INDEX),
        index_untouched=False,
    ),
    # The appended index Text brings the destination it names, and its scene; the save drops the Text.
    "two-indexes": BindingCopyCase(
        CanonicalCandidateOutcome(2, canonical=False, reason=CanonicalCandidateReason.SEVERAL_INDEXES),
        reopened=INDEXED,
        index_untouched=False,
    ),
    # Not copies: a linked binding is library data, and a duplicated object has no manifest naming it.
    "linked-binding": BindingCopyCase(UNIQUE),
    "duplicated-object": BindingCopyCase(UNIQUE),
}


@dataclass
class AmbiguityScene:
    root: Path  # the binding's source
    routes: dict[str, BindingCopyCase]


@contextmanager
def ownership_ambiguity(dest: Path) -> Generator[AmbiguityScene]:
    """F-OWNERSHIP-AMBIGUITY: a source for the binding each route copies, in its own directory under dest."""
    root = copy_scene(Scene.TRANSACTION, dest / "source") / "root.usda"
    yield AmbiguityScene(root=root, routes=dict(ROUTES))
