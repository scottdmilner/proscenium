"""Values the binding-state records hold: time codes and diagnostics (lifecycle.md#binding-state).

Storing the records is tested in tests/blender/test_binding_state.py.
"""

from __future__ import annotations

import pytest
from pxr import Usd

from proscenium.binding.persistence import binding_state
from proscenium.binding.results import Diagnostic, DiagnosticCategory, DiagnosticCode, Severity


def test_time_codes_are_stored_as_their_value_or_none() -> None:
    # The default time code's value is NaN, which would make two equal records unequal.
    assert binding_state.stored_time(Usd.TimeCode.Default()) is None
    assert binding_state.time_code(None).IsDefault()
    assert binding_state.time_code(binding_state.stored_time(Usd.TimeCode(7.25))) == Usd.TimeCode(7.25)


def test_a_diagnostic_rejects_values_it_cannot_hold() -> None:
    with pytest.raises(ValueError, match="not a valid DiagnosticCode"):
        Diagnostic("nonsense", "binding", "m")  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError, match="fields are strings"):
        Diagnostic(DiagnosticCode.UNSAVED_LAYERS, "binding", "m", layers=(1,))  # ty: ignore[invalid-argument-type]
    with pytest.raises(ValueError, match="names its binding"):
        Diagnostic(DiagnosticCode.UNSAVED_LAYERS, "", "m")


def test_the_categories_are_the_specs() -> None:
    # DIAG-01: each category pipeline.md#diagnostics distinguishes is its own value.
    assert {c.value for c in DiagnosticCategory} == {
        "unsupported",
        "approximation",
        "lossy conversion",
        "missing dependency",
        "invalid data",
        "unavailable source",
        "source state",
        "pending cleanup",
        "fatal failure",
    }


@pytest.mark.parametrize("code", list(DiagnosticCode))
def test_a_codes_severity_follows_its_category(code: DiagnosticCode) -> None:
    # Source state is informational; an unavailable source and a fatal failure fail the attempt.
    diagnostic = Diagnostic(code, "binding", "m")
    if diagnostic.category is DiagnosticCategory.SOURCE_STATE:
        assert diagnostic.severity is Severity.INFO
    elif diagnostic.category in (DiagnosticCategory.UNAVAILABLE_SOURCE, DiagnosticCategory.FATAL_FAILURE):
        assert diagnostic.severity is Severity.ERROR
