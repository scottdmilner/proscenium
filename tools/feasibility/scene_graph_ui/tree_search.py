"""Searching a stage for the tree's filter: which prims match a query, and which prims show because of them.

Unlike the UIList's own filter, which hides every row that doesn't match, a search keeps each match's ancestors, so
the matches show in place in the hierarchy. Nothing here imports bpy.
"""

from __future__ import annotations

import enum
import fnmatch
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pxr import Usd
from tree_model import CHILD_PREDICATE

if TYPE_CHECKING:
    from collections.abc import Callable


class SearchMode(enum.Enum):
    """What the query's text is matched against, and how."""

    NAME = "name contains"
    PATH = "path contains"
    GLOB = "name glob"  # fnmatch: * ? [abc]
    REGEX = "path regex"  # re.search on the full path


class SearchFlag(enum.Enum):
    """A fact a prim must have, beyond matching the text."""

    PAYLOAD = "payload"
    VARIANTS = "variants"
    INSTANCE = "instance"
    INACTIVE = "inactive"


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Everything a search matches on; empty fields match every prim."""

    text: str = ""
    mode: SearchMode = SearchMode.NAME
    case_sensitive: bool = False
    type_name: str = ""  # a schema type name, matched with IsA, so "Gprim" finds meshes and curves
    flags: frozenset[SearchFlag] = field(default_factory=frozenset)

    def is_empty(self) -> bool:
        """Whether the query would match every prim, so there's nothing to filter."""
        return not self.text and not self.type_name and not self.flags


@dataclass(frozen=True, slots=True)
class SearchResult:
    """The prims a search found, and those that show because they hold one."""

    matches: frozenset[Usd.Prim]
    shown: frozenset[Usd.Prim]  # the matches and all their ancestors
    truncated: bool  # whether the search stopped at its match cap


class SearchError(ValueError):
    """A query that can't be matched, such as an invalid regular expression."""


def _text_matcher(query: SearchQuery) -> Callable[[Usd.Prim], bool] | None:
    if not query.text:
        return None
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


def matcher(query: SearchQuery) -> Callable[[Usd.Prim], bool]:
    """A test for one prim that a query matches, combining its text, type, and flags."""
    tests: list[Callable[[Usd.Prim], bool]] = []
    text = _text_matcher(query)
    if text is not None:
        tests.append(text)
    if query.type_name:
        schema = Usd.SchemaRegistry.GetTypeFromName(query.type_name)
        if schema.isUnknown:
            raise SearchError(f"no schema type named {query.type_name!r}")
        tests.append(lambda prim: prim.IsA(schema))
    flag_tests = {
        SearchFlag.PAYLOAD: lambda prim: prim.HasPayload(),
        SearchFlag.VARIANTS: lambda prim: bool(prim.GetVariantSets().GetNames()),
        SearchFlag.INSTANCE: lambda prim: prim.IsInstance(),
        SearchFlag.INACTIVE: lambda prim: not prim.IsActive(),
    }
    tests.extend(flag_tests[flag] for flag in query.flags)
    return lambda prim: all(test(prim) for test in tests)


def search(stage: Usd.Stage, query: SearchQuery, cap: int) -> SearchResult:
    """Every prim a query matches, up to cap matches, and the ancestors that show them in place."""
    test = matcher(query)
    matches: set[Usd.Prim] = set()
    shown: set[Usd.Prim] = set()
    truncated = False
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), CHILD_PREDICATE):
        if prim.IsPseudoRoot() or not test(prim):
            continue
        if len(matches) >= cap:
            truncated = True
            break
        matches.add(prim)
        # Walk up until an ancestor already shows: everything above it was added with it.
        ancestor = prim
        while ancestor and not ancestor.IsPseudoRoot() and ancestor not in shown:
            shown.add(ancestor)
            ancestor = ancestor.GetParent()
    return SearchResult(frozenset(matches), frozenset(shown), truncated)
