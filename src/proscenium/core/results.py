"""What operations on a binding report: result states and diagnostics (pipeline.md#diagnostics).

The synchronization API returns them, and the binding-state records store them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ResultState(StrEnum):
    SUCCESS = "success"
    COMPLETED_WITH_ISSUES = "completed with issues"
    FATAL_FAILURE = "fatal failure"


class DiagnosticCategory(StrEnum):
    """Diagnostic categories synchronization reports so far (pipeline.md#diagnostics)."""

    UNAVAILABLE_SOURCE = "unavailable source"
    SOURCE_STATE = "source state"  # informational: it doesn't change the result state
    UNSUPPORTED_RECORD = "unsupported record"  # the binding's configuration can't be read
    REMOVED_DESTINATION = "removed destination"  # fatal: the binding has nowhere to display (lifecycle.md)
    COPIED_BINDING = "copied binding"  # fatal: the binding has copies and no canonical candidate (source-access.md)


class Severity(StrEnum):
    INFO = "info"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One reported problem or state. Also a record field: records store it as a group of strings."""

    category: DiagnosticCategory
    severity: Severity
    message: str
    layers: tuple[str, ...] = ()  # layer identifiers it concerns, sorted

    def __post_init__(self) -> None:
        # A stored diagnostic's enums are plain strings and its layers a list; an unknown value raises ValueError.
        object.__setattr__(self, "category", DiagnosticCategory(self.category))
        object.__setattr__(self, "severity", Severity(self.severity))
        object.__setattr__(self, "layers", tuple(self.layers))
        if type(self.message) is not str or not all(type(layer) is str for layer in self.layers):
            raise TypeError("a diagnostic's message and layers are strings")


@dataclass(frozen=True, slots=True)
class Result:
    """What an operation on a binding did. Expected failures are results, never exceptions."""

    state: ResultState
    diagnostics: tuple[Diagnostic, ...] = ()
