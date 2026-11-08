"""Source-side diagnostics across the boundary (M6 plan, C6).

The core reports each diagnostic by a code from DiagnosticCode, with DIAG-02's fields, and Python builds the binding's
Diagnostic, whose code gives its category and severity (DIAG-14). A projective matrix gets one approximation diagnostic
naming its source path, and the fixtures with valid content plan with none (XFORM-05). Expected values come from the
fixtures' construction.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from fixtures import appearance, evaluation
from proscenium.binding.results import Diagnostic, DiagnosticCategory, DiagnosticCode
from proscenium.binding.source_access.identifiers import BindingId
from proscenium.core import _core
from proscenium.synchronization import evaluation as planning

from .plan_checks import plan_at

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path

BINDING = BindingId("binding")
# Fixtures with no content the core diagnoses: each holds only meshes it translates.
VALID = [evaluation.transforms, evaluation.units_up_axis, evaluation.visibility_purpose, appearance.nested_stress]
CONTENT = {
    DiagnosticCategory.UNSUPPORTED,
    DiagnosticCategory.APPROXIMATION,
    DiagnosticCategory.LOSSY_CONVERSION,
    DiagnosticCategory.MISSING_DEPENDENCY,
    DiagnosticCategory.INVALID_DATA,
}


def test_every_code_the_core_reports_is_a_documented_content_code() -> None:
    codes = _core.diagnostic_codes()
    assert codes and len(set(codes)) == len(codes)
    for code in codes:
        diagnostic = Diagnostic(DiagnosticCode(code), BINDING, "")  # ValueError for a code the list lacks
        assert diagnostic.category in CONTENT, code


def test_a_projective_matrix_is_diagnosed_once_per_prim(tmp_path: Path) -> None:
    # XFORM-05 on F-TRANSFORMS' projective layer: one approximation naming its source path, with no other field, for
    # the mesh, and one for both copies of the mesh inside native instances, naming the first in source order.
    with evaluation.transforms(tmp_path) as transforms:
        plan = plan_at(transforms.projective_stage, 0.0)
    diagnostics = planning.plan_diagnostics(BINDING, plan)
    assert diagnostics == tuple(
        Diagnostic(DiagnosticCode.PROJECTIVE_TRANSFORM, BINDING, d.message, source)
        for d, source in zip(diagnostics, transforms.projective_reported, strict=True)
    )
    assert all(d.category is DiagnosticCategory.APPROXIMATION for d in diagnostics)
    # The instanced mesh's message states how many copies its one diagnostic covers.
    counts = {d.source_path: f"{len(transforms.projective_instanced)} drawn copies" in d.message for d in diagnostics}
    assert counts == {min(transforms.projective_instanced): True, transforms.projective: False}


@pytest.mark.parametrize("generator", VALID)
def test_valid_content_plans_with_no_diagnostics(
    generator: Callable[[Path], AbstractContextManager[Any]], tmp_path: Path
) -> None:
    # The rest of F-TRANSFORMS (XFORM-05), and native instancing the resolver resolves whole.
    with generator(tmp_path) as scene:
        stages = scene.stages.values() if isinstance(scene, evaluation.UnitsScene) else [scene.stage]
        for stage in stages:
            assert plan_at(stage, 0.0).diagnostics == ()


def test_a_code_the_list_lacks_raises() -> None:
    reported = SimpleNamespace(code="no-such-code", source_path="", message="", property_path="", asset="", fallback="")
    plan = cast("_core.Plan", SimpleNamespace(diagnostics=(reported,)))
    with pytest.raises(ValueError, match="no-such-code"):
        planning.plan_diagnostics(BINDING, plan)
