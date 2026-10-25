"""Values the binding-state records hold: time codes and diagnostics (lifecycle.md#binding-state).

Storing the records is tested in tests/blender/test_binding_state.py.
"""

from __future__ import annotations

import pytest
from pxr import Usd

from proscenium.core.results import Diagnostic, DiagnosticCategory, Severity
from proscenium.persistence import binding_state


def test_time_codes_are_stored_as_their_value_or_none() -> None:
    # The default time code's value is NaN, which would make two equal records unequal.
    assert binding_state.stored_time(Usd.TimeCode.Default()) is None
    assert binding_state.time_code(None).IsDefault()
    assert binding_state.time_code(binding_state.stored_time(Usd.TimeCode(7.25))) == Usd.TimeCode(7.25)


def test_a_diagnostic_rejects_values_it_cannot_hold() -> None:
    with pytest.raises(ValueError, match="not a valid DiagnosticCategory"):
        Diagnostic("nonsense", Severity.INFO, "m")  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError, match="message and layers are strings"):
        Diagnostic(DiagnosticCategory.SOURCE_STATE, Severity.INFO, "m", (1,))  # ty: ignore[invalid-argument-type]
