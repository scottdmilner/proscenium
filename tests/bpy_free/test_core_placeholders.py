"""Placeholders, markers, and their diagnostics, through the plan, on F-UNSUPPORTED-CONTENT (M6 plan, C5).

Each untranslated prim, such as the curves and points the spec defers (DEFER-01), is a placeholder with one
untranslated-type diagnostic naming its source path, whose fallback says what stands in: a box of its usable bounds
(MODEL-04), or with none an empty marker, an object holding no data (MODEL-05). Its other behaviors stay (MODEL-03). A
filter's inexact conversion to a mesh is an approximation, and an exact one reports nothing (SNAP-16). Expected values
come from the fixture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fixtures import evaluation
from proscenium.binding.results import Diagnostic, DiagnosticCategory, DiagnosticCode, Severity
from proscenium.binding.source_access import BindingId
from proscenium.synchronization import evaluation as planning

from .plan_checks import assert_world, copies, plan_at

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

BINDING = BindingId("binding")


@pytest.fixture
def unsupported(tmp_path: Path) -> Iterator[evaluation.UnsupportedScene]:
    with evaluation.unsupported_content(tmp_path) as scene:
        yield scene


def _diagnostics(scene: evaluation.UnsupportedScene, code: DiagnosticCode) -> dict[str, Diagnostic]:
    """The plan's diagnostics with the code by source path, each source once."""
    found = [d for d in planning.plan_diagnostics(BINDING, plan_at(scene.stage, 0.0)) if d.code is code]
    by_source = {d.source_path: d for d in found}
    assert len(by_source) == len(found)
    return by_source


def test_each_untranslated_prim_has_one_diagnostic_naming_its_fallback(
    unsupported: evaluation.UnsupportedScene,
) -> None:
    # SNAP-17, MODEL-04, MODEL-05: the basis curves, points, HermiteCurves, and volume.
    untranslated = _diagnostics(unsupported, DiagnosticCode.UNTRANSLATED_TYPE)
    assert untranslated.keys() == unsupported.placeholders.keys()
    for path, expected in unsupported.placeholders.items():
        diagnostic = untranslated[path]
        assert (diagnostic.category, diagnostic.severity) == (DiagnosticCategory.UNSUPPORTED, Severity.WARNING)
        assert diagnostic.fallback_description == (
            "empty marker" if expected.local_bounds is None else "bounding box"
        ), path
        assert expected.type_name in diagnostic.message, path


def test_a_prim_without_usable_bounds_is_an_empty_marker(unsupported: evaluation.UnsupportedScene) -> None:
    # MODEL-05: the volume, with no authored extent and none computed, is an object holding no data at its transform.
    plan = plan_at(unsupported.stage, 0.0)
    shown = copies(plan)
    markers = {path for path, expected in unsupported.placeholders.items() if expected.local_bounds is None}
    assert markers == {"/World/Fog"}
    for path, copy in shown.items():
        assert (copy.bounds_mesh_resource_index is None) == (path in markers), path
    (fog,) = markers
    assert plan.resources[shown[fog].object_resource_index].dependency_resource_indices == ()
    assert_world(shown[fog], unsupported.placeholders[fog].world_matrix)


def test_placeholders_keep_their_other_behaviors(unsupported: evaluation.UnsupportedScene) -> None:
    # MODEL-03: beside its diagnostic, each placeholder has its world transform, participation, and correspondence
    # entry.
    plan = plan_at(unsupported.stage, 0.0)
    shown = copies(plan)
    entries = {c.source_path for c in plan.correspondence}
    for path, expected in unsupported.placeholders.items():
        assert path in entries, path
        assert_world(shown[path], expected.world_matrix)
        assert (shown[path].visible_in_viewport, shown[path].visible_in_render) == (
            expected.visible_in_viewport,
            expected.visible_in_render,
        ), path


def test_inexact_filter_conversions_are_approximations(unsupported: evaluation.UnsupportedScene) -> None:
    # SNAP-16: the Sphere and the NURBS patch are meshes with one approximation each; the Cube, exact, has none.
    approximated = _diagnostics(unsupported, DiagnosticCode.APPROXIMATED_GEOMETRY)
    assert approximated.keys() == unsupported.approximated
    assert all(d.category is DiagnosticCategory.APPROXIMATION for d in approximated.values())
    shown = copies(plan_at(unsupported.stage, 0.0))
    for path in unsupported.approximated | unsupported.exact_conversions:
        assert shown[path].geometry_index >= 0, path  # a provisional mesh, not a placeholder
