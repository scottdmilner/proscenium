"""A result's state derives from its diagnostics, which aggregate repeated problems (pipeline.md#diagnostics)."""

from __future__ import annotations

import pytest

from proscenium.binding import results
from proscenium.binding.results import Diagnostic, DiagnosticCategory, DiagnosticCode, Result, ResultState

DIRTY = Diagnostic(DiagnosticCode.UNSAVED_LAYERS, "binding", "Displaying unsaved edits", layers=("/a.usda",))
UNATTACHED = Diagnostic(DiagnosticCode.NO_ATTACHED_STAGE, "binding", "No stage is attached")
FAILED = Diagnostic(DiagnosticCode.EVALUATION_FAILED, "binding", "Evaluating the source failed")
LEFTOVER = Diagnostic(DiagnosticCode.DISPOSAL_FAILED, "binding", "Couldn't dispose", resource="0" * 32, role="object")


def test_with_no_diagnostics_or_only_source_state_it_succeeds() -> None:
    # DIAG-09: source state is informational.
    assert Result().state is ResultState.SUCCESS
    assert Result(DIRTY).state is ResultState.SUCCESS
    assert Result(DIRTY).is_success


def test_an_unavailable_source_or_a_fatal_failure_is_fatal() -> None:
    # DIAG-11: any fatal diagnostic makes the state fatal, whatever else the result holds.
    assert Result(UNATTACHED).state is ResultState.FATAL_FAILURE
    assert Result(DIRTY, FAILED).state is ResultState.FATAL_FAILURE


def test_each_category_gives_the_state_the_spec_names() -> None:
    # DIAG-09 to DIAG-11. The content and pending-cleanup categories have no codes until a phase reports them, so
    # their state is checked in the table the derivation reads.
    issues = {
        DiagnosticCategory.UNSUPPORTED,
        DiagnosticCategory.APPROXIMATION,
        DiagnosticCategory.LOSSY_CONVERSION,
        DiagnosticCategory.MISSING_DEPENDENCY,
        DiagnosticCategory.INVALID_DATA,
        DiagnosticCategory.PENDING_CLEANUP,
    }
    fatal = {DiagnosticCategory.UNAVAILABLE_SOURCE, DiagnosticCategory.FATAL_FAILURE}
    expected = (
        {c: ResultState.COMPLETED_WITH_ISSUES for c in issues}
        | {c: ResultState.FATAL_FAILURE for c in fatal}
        | {DiagnosticCategory.SOURCE_STATE: ResultState.SUCCESS}
    )
    assert results._STATE_OF == expected  # noqa: SLF001
    assert expected.keys() == set(DiagnosticCategory)


def test_a_repeated_problem_is_one_diagnostic() -> None:
    # DIAG-03: within one result, in the order first reported, with the first report's message.
    reworded = Diagnostic(DiagnosticCode.EVALUATION_FAILED, "binding", "The source couldn't be evaluated")
    assert Result(FAILED, DIRTY, FAILED, reworded).diagnostics == (FAILED, DIRTY)


def test_problems_about_different_things_stay_apart() -> None:
    other_layer = Diagnostic(DiagnosticCode.UNSAVED_LAYERS, "binding", "Displaying unsaved edits", layers=("/b.usda",))
    other_binding = Diagnostic(DiagnosticCode.EVALUATION_FAILED, "other", "Evaluating the source failed")
    assert Result(DIRTY, other_layer, FAILED, other_binding).diagnostics == (
        DIRTY,
        other_layer,
        FAILED,
        other_binding,
    )


def test_the_cleanup_status_never_changes_the_state() -> None:
    # DIAG-15: leftovers an earlier attempt left are reported apart, aggregated; a result's own pending cleanup is its
    # issue.
    result = Result(DIRTY, cleanup_status=(LEFTOVER, LEFTOVER))
    assert result.state is ResultState.SUCCESS
    assert (result.diagnostics, result.cleanup_status) == ((DIRTY,), (LEFTOVER,))
    assert Result(LEFTOVER).state is ResultState.COMPLETED_WITH_ISSUES


def test_a_cleanup_status_holds_only_pending_cleanup() -> None:
    with pytest.raises(ValueError, match="only pending-cleanup"):
        Result(cleanup_status=(DIRTY,))
