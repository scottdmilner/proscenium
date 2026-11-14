"""Matching a search's text against a name or a path: by substring, glob, or regular expression.

A widget's search tests each item it shows, a prim or an attribute, by its name or its path, as the mode says
(`MatchMode.matches_path`), so it reads only the one it needs.
"""

from __future__ import annotations

import enum
import fnmatch
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class MatchMode(enum.Enum):
    """What a search's text is matched against, and how; the value is its label in a search box."""

    NAME = "name contains"
    PATH = "path contains"
    GLOB = "name glob"  # fnmatch: * ? [abc]
    REGEX = "path regex"  # re.search on the full path

    @property
    def matches_path(self) -> bool:
        """Whether the mode matches an item's path, not its name."""
        return self in (MatchMode.PATH, MatchMode.REGEX)


class InvalidPatternError(ValueError):
    """Text that can't be matched in its mode: an invalid regular expression."""


def text_matcher(text: str, mode: MatchMode, case_sensitive: bool) -> Callable[[str], bool]:
    """A test of one name, or one path where the mode matches paths, that the text matches; empty text matches all."""
    if not text:
        return lambda _matched: True
    flags = 0 if case_sensitive else re.IGNORECASE
    if mode is MatchMode.REGEX:
        try:
            pattern = re.compile(text, flags)
        # A repetition count past the engine's limit overflows, and groups nested too deep exceed the compiler's
        # recursion, rather than raising re.error.
        except (re.error, OverflowError, RecursionError) as error:
            raise InvalidPatternError(str(error) or type(error).__name__) from error
        return lambda matched: pattern.search(matched) is not None
    if mode is MatchMode.GLOB:
        pattern = re.compile(fnmatch.translate(text), flags)
        return lambda matched: pattern.match(matched) is not None
    if case_sensitive:
        return lambda matched: text in matched
    needle = text.lower()
    return lambda matched: needle in matched.lower()
