"""The plan's content diagnostics join the attempt's (M6 plan, D3).

On F-UNSUPPORTED-CONTENT, whose untranslated types, approximations, and HermiteCurves warning the fixture states: a
synchronization completes with issues (DIAG-10), its generation and last attempt hold the same diagnostics, an
unchanged one reports them again in the same order (DIAG-07), and a cache call reports its plans' own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from fixtures import evaluation
from proscenium.binding.persistence import binding_state, records
from proscenium.binding.results import DiagnosticCode, ResultState
from support.usd import binding_on_file

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.api.bindings import Bindings
    from proscenium.binding.results import Result


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _expected(unsupported: evaluation.UnsupportedScene) -> set[tuple[DiagnosticCode, str]]:
    """Each content diagnostic the fixture gives, by code and source path."""
    return (
        {(DiagnosticCode.UNTRANSLATED_TYPE, path) for path in unsupported.placeholders}
        | {(DiagnosticCode.APPROXIMATED_GEOMETRY, path) for path in unsupported.approximated}
        | {(DiagnosticCode.USD_WARNING, "/World/Tangents")}  # UsdImaging's HermiteCurves adapter
    )


def _reported(result: Result) -> set[tuple[DiagnosticCode, str]]:
    return {(d.code, d.source_path) for d in result.diagnostics}


def test_content_diagnostics_complete_the_synchronization_with_issues(bindings: Bindings, tmp_path: Path) -> None:
    # DIAG-10 and DIAG-07 on F-UNSUPPORTED-CONTENT "content-diagnostics": each problem once, held by the generation and
    # the last attempt as the result reports it, and equal in the same order when nothing changed.
    with evaluation.unsupported_content(tmp_path) as unsupported:
        handle = binding_on_file(bindings, _scene(), unsupported.root, name="Shot")
        result = handle.synchronize(0)
        assert result.state is ResultState.COMPLETED_WITH_ISSUES
        assert len(result.diagnostics) == len(_expected(unsupported))
        assert _reported(result) == _expected(unsupported)
        destination = bpy.data.collections["Shot"]
        generation = binding_state.read_generation(destination)
        attempt = binding_state.read_last_attempt(destination)
        assert isinstance(generation, records.Loaded) and isinstance(attempt, records.Loaded)
        assert generation.record.diagnostics == attempt.record.diagnostics == result.diagnostics
        assert handle.synchronize(0).diagnostics == result.diagnostics


def test_a_cache_call_reports_its_plans_content_diagnostics(bindings: Bindings, tmp_path: Path) -> None:
    # Each problem once across the call's time codes, as the result aggregates them, the call completing with issues.
    with evaluation.unsupported_content(tmp_path) as unsupported:
        handle = binding_on_file(bindings, _scene(), unsupported.root, name="Shot")
        synchronized = handle.synchronize(0)
        cached = handle.cache([5, 10])
        assert cached.state is ResultState.COMPLETED_WITH_ISSUES
        assert cached.diagnostics == synchronized.diagnostics
