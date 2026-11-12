"""Which children a prim tree lists, and searching a stage for its filter: which prims match, and which show for them.

A tree lists the children `CHILD_PREDICATE` filters, and a search walks the stage by it, so a search finds only prims a
tree can show. Unlike a UIList's own filter, which hides every row that doesn't match, a search keeps each match's
ancestors, so the matches show in place in the hierarchy. It runs over the whole stage, not only the rows already
expanded, or over only the prims it's given, such as the rows a tree shows.
"""

from __future__ import annotations

import enum
import fnmatch
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pxr import Sdf, Usd

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

# Every child a stage editor shows: inactive, unloaded, abstract (class), and undefined (over) prims, and the
# contents of native instances reached through instance proxies.
CHILD_PREDICATE = Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)


def child_count(prim: Usd.Prim) -> int:
    """How many children a prim tree lists under a prim: its children as `CHILD_PREDICATE` filters them."""
    return len(prim.GetFilteredChildren(CHILD_PREDICATE))


class SearchMode(enum.Enum):
    """What the query's text is matched against, and how."""

    NAME = "name contains"
    PATH = "path contains"
    GLOB = "name glob"  # fnmatch: * ? [abc]
    REGEX = "path regex"  # re.search on the full path


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Everything a search matches on; empty text matches every prim."""

    text: str = ""
    mode: SearchMode = SearchMode.NAME
    case_sensitive: bool = False
    # Whether to search only the rows a tree shows without its filter, so the filter expands nothing to show a match;
    # otherwise the whole stage. The tree's view gives the search those rows' prims.
    shown_rows_only: bool = False

    def is_empty(self) -> bool:
        """Whether the query would match every prim, so there's nothing to filter."""
        return not self.text


@dataclass(frozen=True, slots=True)
class SearchResult:
    """The prims a search found, and those that show because they hold one."""

    matching_paths: frozenset[Sdf.Path]
    visible_paths: frozenset[Sdf.Path]  # the matches and all their ancestors, not the pseudo-root
    is_truncated: bool  # whether the search stopped at its match limit


class SearchError(ValueError):
    """A query that can't be matched: an invalid regular expression."""


def matcher(query: SearchQuery) -> Callable[[Usd.Prim], bool]:
    """A test for one prim that a query's text matches; empty text matches every prim."""
    if not query.text:
        return lambda _prim: True
    flags = 0 if query.case_sensitive else re.IGNORECASE
    if query.mode is SearchMode.REGEX:
        try:
            pattern = re.compile(query.text, flags)
        except re.error as error:
            raise SearchError(str(error)) from error
        return lambda prim: pattern.search(str(prim.GetPath())) is not None
    if query.mode is SearchMode.GLOB:
        pattern = re.compile(fnmatch.translate(query.text), flags)
        return lambda prim: pattern.match(prim.GetName()) is not None
    needle = query.text if query.case_sensitive else query.text.lower()
    fold = (lambda text: text) if query.case_sensitive else str.lower
    if query.mode is SearchMode.PATH:
        return lambda prim: needle in fold(str(prim.GetPath()))
    return lambda prim: needle in fold(prim.GetName())


def search(
    stage: Usd.Stage, query: SearchQuery, match_limit: int, candidate_prims: Iterable[Usd.Prim] | None = None
) -> SearchResult:
    """Every prim a query matches, up to match_limit matches, and the ancestors that show them in place.

    It searches candidate_prims if given, in their order, and otherwise every prim on the stage.
    """
    test = matcher(query)
    matching_paths: set[Sdf.Path] = set()
    visible_paths: set[Sdf.Path] = set()
    is_truncated = False
    prims = Usd.PrimRange(stage.GetPseudoRoot(), CHILD_PREDICATE) if candidate_prims is None else candidate_prims
    for prim in prims:
        if prim.IsPseudoRoot() or not test(prim):
            continue
        if len(matching_paths) >= match_limit:
            is_truncated = True
            break
        path = prim.GetPath()
        matching_paths.add(path)
        # Walk up until an ancestor already shows: everything above it was added with it.
        while path != Sdf.Path.absoluteRootPath and path not in visible_paths:
            visible_paths.add(path)
            path = path.GetParentPath()
    return SearchResult(frozenset(matching_paths), frozenset(visible_paths), is_truncated)
