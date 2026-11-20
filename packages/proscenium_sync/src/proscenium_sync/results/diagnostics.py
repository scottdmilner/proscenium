"""What a binding's operations report problems and states with: diagnostics and their codes (pipeline.md#diagnostics).

The binding-state records store them too.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


class DiagnosticCategory(StrEnum):
    """The kinds of problem and state the spec distinguishes (pipeline.md#diagnostics)."""

    UNSUPPORTED = "unsupported"  # valid content the extension doesn't translate
    APPROXIMATION = "approximation"
    LOSSY_CONVERSION = "lossy conversion"
    MISSING_DEPENDENCY = "missing dependency"
    INVALID_DATA = "invalid data"
    UNAVAILABLE_SOURCE = "unavailable source"  # fatal
    SOURCE_STATE = "source state"  # informational: it doesn't change the result state
    VERIFICATION = "verification"  # informational: a capture that differed from a full re-read, under the opt-in mode
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
    # The binding has copies and no canonical candidate, or has copies its removal would leave (source-access.md).
    COPIED_BINDING = "copied-binding"
    EVALUATION_FAILED = "evaluation-failed"  # capturing the evaluated source failed, the planner's errors included
    SOURCE_CHANGED = "source-changed"  # a contributing layer changed during evaluation, so the attempt was discarded
    NEEDS_SYNCHRONIZATION = "needs-synchronization"  # cache found no generation, or a source or scale changed since
    PLANNING_FAILED = "planning-failed"
    # Application's runtime failure: a Blender operation making or keying the display's resources failed, so the
    # attempt was undone; it names the resource when one was being made.
    PREPARATION_FAILED = "preparation-failed"
    # Application's state-change failure: the destination became invalid, as by being removed, during preparation.
    DESTINATION_INVALID = "destination-invalid"
    PUBLICATION_FAILED = "publication-failed"  # publishing, or recording cached time codes, failed, so it was undone
    DISPOSAL_FAILED = "disposal-failed"  # a prepared resource couldn't be removed, so it's pending cleanup
    RETIREMENT_FAILED = "retirement-failed"  # an obsolete resource couldn't be removed, so it's pending cleanup
    CLEANUP_FAILED = "cleanup-failed"  # a cleanup retry resolved nothing
    REMOVAL_FAILED = "removal-failed"  # removing a binding couldn't remove a managed resource, so it's pending cleanup
    # The destination is also linked into a scene whose unit scale differs from the target scene's, which the display
    # is planned for (transforms.md#coordinate-conversion).
    CAPTURE_MISMATCH = "capture-mismatch"  # an incremental capture differed from a full re-read (verification mode)
    UNIT_SCALE_MISMATCH = "unit-scale-mismatch"
    # Source-side content, which the planner reports (planner.diagnostics.h).
    PROJECTIVE_TRANSFORM = "projective-transform"  # a world transform placed by its affine part
    UNSUPPORTED_INSTANCING = "unsupported-instancing"  # instancing Hydra gives that isn't translated
    INVALID_INSTANCER = "invalid-instancer"  # instancing data that can't be resolved
    USD_WARNING = "usd-warning"  # a Tf warning USD or Hydra posted reading the source: mostly something declined
    USD_ERROR = "usd-error"  # a Tf error USD or Hydra posted reading the source: content it couldn't read
    UNTRANSLATED_TYPE = "untranslated-type"  # a type not translated, shown by a placeholder or marker (its fallback)
    APPROXIMATED_GEOMETRY = "approximated-geometry"  # a filter's inexact conversion to a mesh, such as a sphere's


# The codes the planner reports, whose messages state their problems (Diagnostic.aggregation_key);
# synchronization.evaluation checks the planner's list against it on import.
PLANNER_CODES = frozenset(
    {
        DiagnosticCode.PROJECTIVE_TRANSFORM,
        DiagnosticCode.UNSUPPORTED_INSTANCING,
        DiagnosticCode.INVALID_INSTANCER,
        DiagnosticCode.USD_WARNING,
        DiagnosticCode.USD_ERROR,
        DiagnosticCode.UNTRANSLATED_TYPE,
        DiagnosticCode.APPROXIMATED_GEOMETRY,
    }
)

_KINDS: dict[DiagnosticCode, tuple[DiagnosticCategory, Severity]] = {
    DiagnosticCode.UNSAVED_LAYERS: (DiagnosticCategory.SOURCE_STATE, Severity.INFO),
    DiagnosticCode.NO_ATTACHED_STAGE: (DiagnosticCategory.UNAVAILABLE_SOURCE, Severity.ERROR),
    DiagnosticCode.SOURCE_CONFIRMATION_REQUIRED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.UNSUPPORTED_RECORD: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.COPIED_BINDING: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.EVALUATION_FAILED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.SOURCE_CHANGED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.NEEDS_SYNCHRONIZATION: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.PLANNING_FAILED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.PREPARATION_FAILED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.DESTINATION_INVALID: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.CAPTURE_MISMATCH: (DiagnosticCategory.VERIFICATION, Severity.INFO),
    DiagnosticCode.UNIT_SCALE_MISMATCH: (DiagnosticCategory.LOSSY_CONVERSION, Severity.WARNING),
    DiagnosticCode.PUBLICATION_FAILED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.DISPOSAL_FAILED: (DiagnosticCategory.PENDING_CLEANUP, Severity.WARNING),
    DiagnosticCode.RETIREMENT_FAILED: (DiagnosticCategory.PENDING_CLEANUP, Severity.WARNING),
    DiagnosticCode.CLEANUP_FAILED: (DiagnosticCategory.FATAL_FAILURE, Severity.ERROR),
    DiagnosticCode.REMOVAL_FAILED: (DiagnosticCategory.PENDING_CLEANUP, Severity.WARNING),
    DiagnosticCode.PROJECTIVE_TRANSFORM: (DiagnosticCategory.APPROXIMATION, Severity.WARNING),
    DiagnosticCode.UNSUPPORTED_INSTANCING: (DiagnosticCategory.UNSUPPORTED, Severity.WARNING),
    DiagnosticCode.INVALID_INSTANCER: (DiagnosticCategory.INVALID_DATA, Severity.WARNING),
    DiagnosticCode.USD_WARNING: (DiagnosticCategory.UNSUPPORTED, Severity.WARNING),
    DiagnosticCode.USD_ERROR: (DiagnosticCategory.INVALID_DATA, Severity.WARNING),
    DiagnosticCode.UNTRANSLATED_TYPE: (DiagnosticCategory.UNSUPPORTED, Severity.WARNING),
    DiagnosticCode.APPROXIMATED_GEOMETRY: (DiagnosticCategory.APPROXIMATION, Severity.WARNING),
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
    asset_identifier: str = ""  # the asset it concerns, as authored
    fallback_description: str = ""  # what is displayed in its place
    layer_identifiers: tuple[str, ...] = ()  # layer identifiers it concerns, sorted
    pending_resource_key: str = ""  # for pending cleanup, the ledger key of the pending resource it concerns
    role: str = ""  # the representation role of the resource it concerns: a pending one, or one that failed

    def __post_init__(self) -> None:
        # A stored diagnostic's code is a plain string and its layers a list; an unknown code raises ValueError.
        object.__setattr__(self, "code", DiagnosticCode(self.code))
        object.__setattr__(self, "layer_identifiers", tuple(self.layer_identifiers))
        texts = (
            self.binding_id,
            self.message,
            self.source_path,
            self.property_path,
            self.asset_identifier,
            self.fallback_description,
        )
        if not all(
            type(text) is str for text in (*texts, self.pending_resource_key, self.role, *self.layer_identifiers)
        ):
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
    def aggregation_key(self) -> tuple[object, ...]:
        """The identity used to deduplicate reports of the same problem (DIAG-03).

        The planner's message states its problem, a Tf warning's text or the type left untranslated, so it is part of
        the problem; another's is prose about one, so it isn't.
        """
        worded = self.code in PLANNER_CODES
        return tuple(getattr(self, f.name) for f in fields(self) if worded or f.name != "message")


def deduplicated_diagnostics(diagnostics: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    """The diagnostics with each problem once, in the order first reported (DIAG-03).

    A problem is a diagnostic's code and everything it concerns; its message is prose, so a repeat with another
    message is the same problem, and the first report's message is kept.
    """
    first: dict[tuple[object, ...], Diagnostic] = {}
    for diagnostic in diagnostics:
        first.setdefault(diagnostic.aggregation_key, diagnostic)
    return tuple(first.values())
