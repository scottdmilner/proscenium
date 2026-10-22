"""F-OWNERSHIP-AMBIGUITY: copied bindings on each copy route, and binding indexes lost, cleared, duplicated,
disagreeing, or unreadable (source-access.md#copied-bindings, source-access.md#canonical-candidate).

The routes are Blender operations, and the generator runs without bpy, so it gives a binding's source and,
for each route, the outcome the canonical-candidate rule gives what that route leaves, derived from the
rule and the route (D1 in docs/plans/M03-bindings.md), never from running it; tests/support/copies.py
runs the routes, on a binding "Shot" on the scene "Scene" whose destination holds the managed object
"Managed". Candidates are counted as the rule counts them: binding records, then tagged collections no
record names.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from proscenium.core.copies import Reason

from .scenes import Scene, copy_scene

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@dataclass(frozen=True)
class Outcome:
    candidates: int  # the identity's candidates after the route
    canonical: bool  # whether the original stays canonical; False: every candidate is disabled
    reason: Reason


@dataclass(frozen=True)
class Route:
    outcome: Outcome
    reopened: Outcome | None = None  # after save and reopen, where it differs
    index_untouched: bool = True  # the file keeps one index, whose entry names the original destination


INDEXED = Outcome(2, canonical=True, reason=Reason.INDEXED)
UNIQUE = Outcome(1, canonical=True, reason=Reason.UNIQUE)

ROUTES: dict[str, Route] = {
    # Copy routes: the index names the original, whose record and destination refer to each other.
    "collection-copy": Route(INDEXED),  # Collection.copy(): a tagged collection no record names
    "deep-collection-copy": Route(INDEXED),  # Outliner > Duplicate Collection's inferred state (D1), by hand
    "full-copy-scene": Route(INDEXED),  # a second scene and destination referring to each other
    "linked-copy-scene": Route(INDEXED),  # a second scene's record naming the original destination
    "append": Route(INDEXED),  # the destination appended from a copy of the file brings its scene
    "record-copy": Route(Outcome(3, canonical=True, reason=Reason.INDEXED)),  # records assigned by script
    # The index lost, cleared, or disagreeing: the fallback, or nothing, decides.
    "index-lost": Route(Outcome(2, canonical=False, reason=Reason.SEVERAL_MUTUAL), index_untouched=False),
    "index-lost-linked-copy": Route(Outcome(2, canonical=True, reason=Reason.MUTUAL), index_untouched=False),
    "entry-cleared": Route(Outcome(2, canonical=True, reason=Reason.MUTUAL), index_untouched=False),
    "none-mutual": Route(Outcome(2, canonical=False, reason=Reason.NONE_MUTUAL), index_untouched=False),
    "index-disagrees": Route(Outcome(2, canonical=False, reason=Reason.INDEX_DISAGREES), index_untouched=False),
    "unreadable-index": Route(Outcome(2, canonical=False, reason=Reason.UNREADABLE_INDEX), index_untouched=False),
    # The appended index Text brings the destination it names, and its scene; the save drops the Text.
    "two-indexes": Route(
        Outcome(2, canonical=False, reason=Reason.SEVERAL_INDEXES), reopened=INDEXED, index_untouched=False
    ),
    # Not copies: a linked binding is library data, and a duplicated object has no manifest naming it.
    "linked-binding": Route(UNIQUE),
    "duplicated-object": Route(UNIQUE),
}


@dataclass
class AmbiguityScene:
    root: Path  # the binding's source
    routes: dict[str, Route]


@contextmanager
def ownership_ambiguity(dest: Path) -> Generator[AmbiguityScene]:
    """F-OWNERSHIP-AMBIGUITY: a source for the binding each route copies, in its own directory under dest."""
    root = copy_scene(Scene.SOURCE_ACCESS, dest / "source") / "root.usda"
    yield AmbiguityScene(root=root, routes=dict(ROUTES))
