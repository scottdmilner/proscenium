"""What operations on a binding report: result states and diagnostics (pipeline.md#diagnostics).

The synchronization API returns them, and the binding-state records store them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
    UNSUPPORTED_RECORD = "unsupported-record"  # the binding's configuration can't be read
    REMOVED_DESTINATION = "removed-destination"  # the binding has nowhere to display (lifecycle.md)
    COPIED_BINDING = "copied-binding"  # the binding has copies and no canonical candidate (source-access.md)


_KINDS: dict[DiagnosticCode, tuple[DiagnosticCategory, Severity]] = {
    DiagnosticCode.UNSAVED_LAYERS: (DiagnosticCategory.SOURCE_STATE, Severity.INFO),
    DiagnosticCode.NO_ATTACHED_STAGE: (DiagnosticCategory.UNAVAILABLE_SOURCE, Severity.ERROR),
    DiagnosticCode.SOURCE_CONFIRMATION_REQUIRED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.UNSUPPORTED_RECORD: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.REMOVED_DESTINATION: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.COPIED_BINDING: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
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
    resource: str = ""  # the entry key of the managed resource it concerns, for pending cleanup
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


@dataclass(frozen=True, slots=True)
class Result:
    """What an operation on a binding did. Expected failures are results, never exceptions."""

    state: ResultState
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def is_success(self) -> bool:
        """Whether the operation succeeded."""
        return self.state == ResultState.SUCCESS
