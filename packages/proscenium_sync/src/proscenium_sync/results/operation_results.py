"""What an operation on a binding did: a result, whose state derives from its diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from .diagnostics import Diagnostic, DiagnosticCategory, deduplicated_diagnostics

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pxr import Usd


class ResultState(StrEnum):
    """How an operation ended: its result's state."""

    SUCCESS = "success"
    COMPLETED_WITH_ISSUES = "completed with issues"
    FATAL_FAILURE = "fatal failure"


# The state each category gives a result on its own (pipeline.md#diagnostics); a result's is its worst diagnostic's.
_STATE_OF: dict[DiagnosticCategory, ResultState] = {
    DiagnosticCategory.SOURCE_STATE: ResultState.SUCCESS,
    DiagnosticCategory.VERIFICATION: ResultState.SUCCESS,
    DiagnosticCategory.UNSUPPORTED: ResultState.COMPLETED_WITH_ISSUES,
    DiagnosticCategory.APPROXIMATION: ResultState.COMPLETED_WITH_ISSUES,
    DiagnosticCategory.LOSSY_CONVERSION: ResultState.COMPLETED_WITH_ISSUES,
    DiagnosticCategory.MISSING_DEPENDENCY: ResultState.COMPLETED_WITH_ISSUES,
    DiagnosticCategory.INVALID_DATA: ResultState.COMPLETED_WITH_ISSUES,
    DiagnosticCategory.PENDING_CLEANUP: ResultState.COMPLETED_WITH_ISSUES,
    DiagnosticCategory.UNAVAILABLE_SOURCE: ResultState.FATAL_FAILURE,
    DiagnosticCategory.FATAL_FAILURE: ResultState.FATAL_FAILURE,
}
_WORSE = (ResultState.SUCCESS, ResultState.COMPLETED_WITH_ISSUES, ResultState.FATAL_FAILURE)


def result_state(diagnostics: Iterable[Diagnostic]) -> ResultState:
    """The state an operation with these diagnostics ends in: its worst diagnostic's, or success with none."""
    return max((_STATE_OF[d.category] for d in diagnostics), key=_WORSE.index, default=ResultState.SUCCESS)


@dataclass(frozen=True, slots=True, init=False)
class Result:
    """What an operation on a binding did. Expected failures are results, never exceptions.

    Its diagnostics are its own, aggregated, and its state derives from them. Its cleanup status is the binding's
    pending cleanup as the operation ended, which an earlier attempt may have left, so it never changes the state
    (DIAG-06, DIAG-15).
    """

    diagnostics: tuple[Diagnostic, ...]
    # Those it attempted: a synchronization's one, none for most operations.
    attempted_time_codes: tuple[Usd.TimeCode, ...]
    pending_cleanup_diagnostics: tuple[Diagnostic, ...]  # the binding's current cleanup diagnostics, aggregated

    def __init__(
        self,
        *diagnostics: Diagnostic,
        attempted_time_codes: Iterable[Usd.TimeCode] = (),
        pending_cleanup_diagnostics: Iterable[Diagnostic] = (),
    ) -> None:
        object.__setattr__(self, "diagnostics", deduplicated_diagnostics(diagnostics))
        object.__setattr__(self, "attempted_time_codes", tuple(attempted_time_codes))
        object.__setattr__(self, "pending_cleanup_diagnostics", deduplicated_diagnostics(pending_cleanup_diagnostics))
        if any(d.category is not DiagnosticCategory.PENDING_CLEANUP for d in self.pending_cleanup_diagnostics):
            raise ValueError("a cleanup status holds only pending-cleanup diagnostics")

    @property
    def state(self) -> ResultState:
        """How the operation ended."""
        return result_state(self.diagnostics)

    @property
    def is_success(self) -> bool:
        """Whether the operation succeeded."""
        return self.state == ResultState.SUCCESS


class DiagnosticCollector:
    """The diagnostics an operation reports as its steps run, in order, for its result."""

    _reported: list[Diagnostic]

    def __init__(self) -> None:
        self._reported = []

    def add(self, diagnostic: Diagnostic) -> None:
        """Report diagnostic."""
        self._reported.append(diagnostic)

    def extend(self, diagnostics: Iterable[Diagnostic]) -> None:
        """Report each of diagnostics, in order."""
        self._reported.extend(diagnostics)

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        """Those reported so far, aggregated as a result's are (DIAG-03)."""
        return deduplicated_diagnostics(self._reported)

    def result(self, *, attempted_time_codes: Iterable[Usd.TimeCode] = ()) -> Result:
        """A result holding those reported so far."""
        return Result(*self._reported, attempted_time_codes=attempted_time_codes)
