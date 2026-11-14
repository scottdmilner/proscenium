"""Which of a prim's properties a property list shows: a search's text, matched against each property, and a filter.

Unlike the scene graph's search, nothing shows for holding a match: a property list is flat, so each property shows
if it matches, and a relationship's targets show under it when it's expanded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...widget_model import text_matching

if TYPE_CHECKING:
    from collections.abc import Callable

    from pxr import Usd


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Everything a property list's search matches on; empty text matches every property."""

    text: str = ""
    mode: text_matching.MatchMode = text_matching.MatchMode.NAME
    case_sensitive: bool = False
    # Whether to show only properties with opinions, leaving out the schema's fallbacks; on unless turned off.
    authored_only: bool = True

    def is_empty(self) -> bool:
        """Whether the query would show every property, so there's nothing to filter."""
        return not self.text and not self.authored_only


def matcher(query: SearchQuery) -> Callable[[Usd.Property], bool]:
    """A test for one property that a query shows it: its text matches its name or path, as its mode says.

    Raises text_matching.InvalidPatternError for text its mode can't match.
    """
    test = text_matching.text_matcher(query.text, query.mode, query.case_sensitive)
    if query.mode.matches_path:

        def matches_text(prop: Usd.Property) -> bool:
            return test(str(prop.GetPath()))
    else:

        def matches_text(prop: Usd.Property) -> bool:
            return test(prop.GetName())

    if not query.authored_only:
        return matches_text
    return lambda prop: prop.IsAuthored() and matches_text(prop)
