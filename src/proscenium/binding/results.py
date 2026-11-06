"""What operations on a binding report: result states and diagnostics (pipeline.md#diagnostics).

The synchronization API returns them, and the binding-state records store them.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pxr import Usd


class ResultState(StrEnum):
    """How an operation ended: its result's state."""

    SUCCESS = "success"
    COMPLETED_WITH_ISSUES = "completed with issues"
    FATAL_FAILURE = "fatal failure"


class DiagnosticCategory(StrEnum):
    """The kinds of problem and state the spec distinguishes (pipeline.md#diagnostics)."""

    UNSUPPORTED = "unsupported"  # valid content the extension doesn't translate
    APPROXIMATION = "approximation"
    LOSSY_CONVERSION = "lossy conversion"
    MISSING_DEPENDENCY = "missing dependency"
    INVALID_DATA = "invalid data"
    UNAVAILABLE_SOURCE = "unavailable source"  # fatal
    SOURCE_STATE = "source state"  # informational: it doesn't change the result state
    PENDING_CLEANUP = "pending cleanup"  # retryable disposal of prepared or obsolete resources
    FATAL_FAILURE = "fatal failure"


class Severity(StrEnum):
    """How serious a diagnostic is."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticCode(StrEnum):
    """The stable code naming a diagnostic's problem, which callers and tests identify it by (DIAG-14).

    Each code has one category and one severity (Diagnostic.category, Diagnostic.severity).
    """

    UNSAVED_LAYERS = "unsaved-layers"  # layers displayed with unsaved in-process edits
    NO_ATTACHED_STAGE = "no-attached-stage"
    SOURCE_CONFIRMATION_REQUIRED = "source-confirmation-required"  # an attachment's root-layer identifier changed
    UNSUPPORTED_RECORD = "unsupported-record"  # a record the binding's operation needs can't be read
    COPIED_BINDING = "copied-binding"  # the binding has copies and no canonical candidate (source-access.md)
    EVALUATION_FAILED = "evaluation-failed"  # capturing the evaluated source failed, the core's errors included
    SOURCE_CHANGED = "source-changed"  # a contributing layer changed during evaluation, so the attempt was discarded
    PLANNING_FAILED = "planning-failed"
    PREPARATION_FAILED = "preparation-failed"  # making or keying the display's resources failed, so it was undone
    PUBLICATION_FAILED = "publication-failed"  # publishing, or recording cached time codes, failed, so it was undone
    DISPOSAL_FAILED = "disposal-failed"  # a prepared resource couldn't be removed, so it's pending cleanup
    RETIREMENT_FAILED = "retirement-failed"  # an obsolete resource couldn't be removed, so it's pending cleanup
    CLEANUP_FAILED = "cleanup-failed"  # a cleanup retry resolved nothing


_KINDS: dict[DiagnosticCode, tuple[DiagnosticCategory, Severity]] = {
    DiagnosticCode.UNSAVED_LAYERS: (DiagnosticCategory.SOURCE_STATE, Severity.INFO),
    DiagnosticCode.NO_ATTACHED_STAGE: (DiagnosticCategory.UNAVAILABLE_SOURCE, Severity.ERROR),
    DiagnosticCode.SOURCE_CONFIRMATION_REQUIRED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.UNSUPPORTED_RECORD: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.COPIED_BINDING: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.EVALUATION_FAILED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.SOURCE_CHANGED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.PLANNING_FAILED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.PREPARATION_FAILED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.PUBLICATION_FAILED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.DISPOSAL_FAILED: (DiagnosticCategory.PENDING_CLEANUP, Severity.WARNING),
    DiagnosticCode.RETIREMENT_FAILED: (DiagnosticCategory.PENDING_CLEANUP, Severity.WARNING),
    DiagnosticCode.CLEANUP_FAILED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
}


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One reported problem or state. Also a record field: records store it as a group of strings.

    The fields that don't apply to it are empty (DIAG-02).
    """

    code: DiagnosticCode
    binding_id: str  # a BindingId: the binding it was reported for
    message: str
    source_path: str = ""  # the source entity it concerns, as a composed-stage path
    property_path: str = ""  # the property it concerns
    asset: str = ""  # the asset it concerns, as authored
    fallback: str = ""  # what is displayed in its place
    layers: tuple[str, ...] = ()  # layer identifiers it concerns, sorted
    resource: str = ""  # for pending cleanup, the ledger key of the pending resource it concerns
    role: str = ""  # that resource's representation role

    def __post_init__(self) -> None:
        # A stored diagnostic's code is a plain string and its layers a list; an unknown code raises ValueError.
        object.__setattr__(self, "code", DiagnosticCode(self.code))
        object.__setattr__(self, "layers", tuple(self.layers))
        texts = (self.binding_id, self.message, self.source_path, self.property_path, self.asset, self.fallback)
        if not all(type(text) is str for text in (*texts, self.resource, self.role, *self.layers)):
            raise TypeError("a diagnostic's fields are strings")
        if not self.binding_id:
            raise ValueError("a diagnostic names its binding")

    @property
    def category(self) -> DiagnosticCategory:
        """The kind of problem or state its code names."""
        return _KINDS[self.code][0]

    @property
    def severity(self) -> Severity:
        """How serious its code is."""
        return _KINDS[self.code][1]

    @property
    def problem(self) -> tuple[object, ...]:
        """What it reports, apart from how its message words it: repeats of one problem aggregate (DIAG-03)."""
        return tuple(getattr(self, f.name) for f in fields(self) if f.name != "message")


# The state each category gives a result on its own (pipeline.md#diagnostics); a result's is its worst diagnostic's.
_STATE_OF: dict[DiagnosticCategory, ResultState] = {
    DiagnosticCategory.SOURCE_STATE: ResultState.SUCCESS,
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


def aggregated(diagnostics: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    """The diagnostics with each problem once, in the order first reported (DIAG-03).

    A problem is a diagnostic's code and everything it concerns; its message is prose, so a repeat with another
    message is the same problem, and the first report's message is kept.
    """
    first: dict[tuple[object, ...], Diagnostic] = {}
    for diagnostic in diagnostics:
        first.setdefault(diagnostic.problem, diagnostic)
    return tuple(first.values())


@dataclass(frozen=True, slots=True, init=False)
class Result:
    """What an operation on a binding did. Expected failures are results, never exceptions.

    Its diagnostics are its own, aggregated, and its state derives from them. Its cleanup status is the binding's
    pending cleanup as the operation ended, which an earlier attempt may have left, so it never changes the state
    (DIAG-06, DIAG-15).
    """

    diagnostics: tuple[Diagnostic, ...]
    time_codes: tuple[Usd.TimeCode, ...]  # those it attempted: a synchronization's one, none for most operations
    cleanup_status: tuple[Diagnostic, ...]  # the binding's current cleanup diagnostics, aggregated

    def __init__(
        self,
        *diagnostics: Diagnostic,
        time_codes: Iterable[Usd.TimeCode] = (),
        cleanup_status: Iterable[Diagnostic] = (),
    ) -> None:
        object.__setattr__(self, "diagnostics", aggregated(diagnostics))
        object.__setattr__(self, "time_codes", tuple(time_codes))
        object.__setattr__(self, "cleanup_status", aggregated(cleanup_status))
        if any(d.category is not DiagnosticCategory.PENDING_CLEANUP for d in self.cleanup_status):
            raise ValueError("a cleanup status holds only pending-cleanup diagnostics")

    @property
    def state(self) -> ResultState:
        """How the operation ended."""
        return result_state(self.diagnostics)

    @property
    def is_success(self) -> bool:
        """Whether the operation succeeded."""
        return self.state == ResultState.SUCCESS
