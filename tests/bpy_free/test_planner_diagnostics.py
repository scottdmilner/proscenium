"""Source-side diagnostics across the boundary (M6 plan, C6).

The planner reports each diagnostic by a code from DiagnosticCode, with DIAG-02's fields, and Python builds the
binding's Diagnostic, whose code gives its category and severity (DIAG-14). A projective matrix gets one approximation
diagnostic naming its source path, and the fixtures with valid content plan with none (XFORM-05). Expected values come
from the fixtures' construction.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from pxr import Usd, UsdGeom

from fixtures import appearance, evaluation
from proscenium_sync import planner, results
from proscenium_sync.results import Diagnostic, DiagnosticCategory, DiagnosticCode
from proscenium_sync.source_access import BindingId
from proscenium_sync.synchronization import evaluation as planning

from .plan_checks import CONTEXT, SETTINGS, plan_at

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path

BINDING = BindingId("binding")
# Fixtures with no content the planner diagnoses: each holds only meshes it translates.
VALID = [evaluation.transforms, evaluation.units_up_axis, evaluation.visibility_purpose, appearance.nested_stress]
CONTENT = {
    DiagnosticCategory.UNSUPPORTED,
    DiagnosticCategory.APPROXIMATION,
    DiagnosticCategory.LOSSY_CONVERSION,
    DiagnosticCategory.MISSING_DEPENDENCY,
    DiagnosticCategory.INVALID_DATA,
}


def test_every_code_the_planner_reports_is_a_documented_content_code() -> None:
    codes = planner.diagnostic_codes()
    assert codes and len(set(codes)) == len(codes)
    assert set(codes) == results.PLANNER_CODES  # the codes whose wording is part of their problem
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
        for d, source in zip(diagnostics, transforms.projective_diagnostic_sources, strict=True)
    )
    assert all(d.category is DiagnosticCategory.APPROXIMATION for d in diagnostics)
    # The instanced mesh's message states how many copies its one diagnostic covers.
    counts = {
        d.source_path: f"{len(transforms.projective_instance_world_matrices)} drawn copies" in d.message
        for d in diagnostics
    }
    assert counts == {min(transforms.projective_instance_world_matrices): True, transforms.projective_mesh_path: False}


@pytest.mark.parametrize("generator", VALID)
def test_valid_content_plans_with_no_diagnostics(
    generator: Callable[[Path], AbstractContextManager[Any]], tmp_path: Path
) -> None:
    # The rest of F-TRANSFORMS (XFORM-05), and native instancing the resolver resolves whole.
    with generator(tmp_path) as scene:
        stages = scene.stages.values() if isinstance(scene, evaluation.UnitsScene) else [scene.stage]
        for stage in stages:
            assert plan_at(stage, 0.0).diagnostics == ()


def _usd_warnings(plan: planner.Plan) -> list[Diagnostic]:
    return [d for d in planning.plan_diagnostics(BINDING, plan) if d.code is DiagnosticCode.USD_WARNING]


def test_a_warning_usd_posts_while_capturing_names_its_prim(tmp_path: Path) -> None:
    # UsdImaging warns that its HermiteCurves adapter has no data-source support, on F-UNSUPPORTED-CONTENT's Tangents,
    # while the chain is built and again whenever a capture lists Tangents' children: one diagnostic per capture,
    # naming Tangents, through one chain and its later captures alike.
    with evaluation.unsupported_content(tmp_path) as unsupported:
        chain = planner.SceneIndexChain(unsupported.stage)
        try:
            plans = [planner.plan(chain.capture(Usd.TimeCode(t)), SETTINGS, CONTEXT) for t in (0.0, 1.0, 1.0)]
        finally:
            chain.release()
    for plan in plans:
        (warning,) = _usd_warnings(plan)
        assert (warning.source_path, warning.category) == ("/World/Tangents", DiagnosticCategory.UNSUPPORTED)


def test_a_warning_inside_a_prototype_is_reported_once_per_usd_prim(tmp_path: Path) -> None:
    # Two HermiteCurves in F-NESTED-STRESS' Leaf prototype, which Hydra's instance aggregation splits into several
    # prototypes of its own: one warning for each, for all of its copies, naming the first in source order and counting
    # them.
    names = ("Strand", "Wisp")
    with appearance.nested_stress(tmp_path) as stress:
        stage = stress.stage
        for name in names:
            stage.DefinePrim(f"/Prototypes/Leaf/{name}", "HermiteCurves")
        copies = {
            name: sorted(
                str(prim.GetPath())
                for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())
                if prim.GetName() == name and prim.IsInstanceProxy()
            )
            for name in names
        }
        diagnostics = planning.plan_diagnostics(BINDING, plan_at(stage, 0.0))
    # UsdImaging's warning, and the planner's untranslated-type, each once per prim.
    for code in (DiagnosticCode.USD_WARNING, DiagnosticCode.UNTRANSLATED_TYPE):
        reported = [d for d in diagnostics if d.code is code]
        assert {d.source_path: f"{len(copies['Strand'])} drawn copies" in d.message for d in reported} == {
            sources[0]: True for sources in copies.values()
        }, code
    assert all(len(sources) == 6 for sources in copies.values())


LISTED = 10  # the diagnostics one problem gets before one counts the rest (with the user; diagnostics.h)


def test_a_problem_on_many_prims_lists_its_first_and_counts_the_rest(tmp_path: Path) -> None:
    # DIAG-16 on F-UNSUPPORTED-CONTENT, with 25 more BasisCurves beside its own: of the BasisCurves boxes' one problem,
    # an untranslated-type for each of the first ten in source order, then one naming no source and counting the
    # rest; the other types' problems stay their own.
    with evaluation.unsupported_content(tmp_path) as unsupported:
        stage = unsupported.stage
        added = [f"/World/Many/Curves{i:02}" for i in range(25)]
        for path in added:
            UsdGeom.BasisCurves.Define(stage, path).CreateExtentAttr([(0, 0, 0), (1, 1, 1)])
        diagnostics = planning.plan_diagnostics(BINDING, plan_at(stage, 0.0))
    curves = sorted([p for p, box in unsupported.placeholders.items() if box.type_name == "BasisCurves"] + added)
    untranslated = [d for d in diagnostics if d.code is DiagnosticCode.UNTRANSLATED_TYPE]
    boxed = [d for d in untranslated if "BasisCurves" in d.message]
    assert [d.source_path for d in boxed] == [*curves[:LISTED], ""]
    assert boxed[-1].message.endswith(f"(and {len(curves) - LISTED} more with the same problem, not listed)")
    assert boxed[-1].fallback_description == "bounding box"
    others = {p for p, box in unsupported.placeholders.items() if box.type_name != "BasisCurves"}
    assert {d.source_path for d in untranslated if d not in boxed} == others


def test_a_code_the_list_lacks_raises() -> None:
    reported = SimpleNamespace(
        code="no-such-code", source_path="", message="", property_path="", asset_identifier="", fallback_description=""
    )
    plan = cast("planner.Plan", SimpleNamespace(diagnostics=(reported,)))
    with pytest.raises(ValueError, match="no-such-code"):
        planning.plan_diagnostics(BINDING, plan)


def test_a_problem_lists_its_first_ten_sources(tmp_path: Path) -> None:
    # Fourteen instanced curves and the fixture's Tangents, which Hydra reports before them: the first ten in source
    # order are listed, and the other five counted.
    with evaluation.unsupported_content(tmp_path) as unsupported:
        stage = unsupported.stage
        for index in range(14):
            definition = stage.CreateClassPrim(f"/Definitions/Curve{index:02}")
            curve = stage.DefinePrim(f"{definition.GetPath()}/Strand", "HermiteCurves")
            UsdGeom.Boundable(curve).CreateExtentAttr([(0, 0, 0), (1, 1, 1)])
            instance = stage.DefinePrim(f"/World/I{index:02}")
            instance.GetReferences().AddInternalReference(definition.GetPath())
            instance.SetInstanceable(True)
        diagnostics = planning.plan_diagnostics(BINDING, plan_at(stage, 0.0))
    for code in (DiagnosticCode.USD_WARNING, DiagnosticCode.UNTRANSLATED_TYPE):  # from capture, and from planning
        reports = [d for d in diagnostics if d.code is code and "HermiteCurves" in d.message]
        assert [d.source_path for d in reports] == [*(f"/World/I{i:02}/Strand" for i in range(LISTED)), ""]
        assert reports[-1].message.endswith("(and 5 more with the same problem, not listed)")


def test_point_copies_are_reported_with_the_definition_they_copy(tmp_path: Path) -> None:
    # Each curve is drawn itself and twice by each of two point instancers: one report each, covering five copies.
    with evaluation.unsupported_content(tmp_path) as unsupported:
        stage = unsupported.stage
        subjects = ["/World/CanonicalCurve", "/World/OtherCurve"]
        for path in subjects:
            curve = stage.DefinePrim(path, "BasisCurves")
            UsdGeom.Boundable(curve).CreateExtentAttr([(0, 0, 0), (1, 1, 1)])
        for name in ("ZCopiesA", "ZCopiesB"):
            instancer = UsdGeom.PointInstancer.Define(stage, f"/World/{name}")
            instancer.CreatePrototypesRel().SetTargets(subjects)
            instancer.CreateProtoIndicesAttr([0, 1, 0, 1])
            instancer.CreatePositionsAttr([(i * 2, 0, 0) for i in range(4)])
        chain = planner.SceneIndexChain(stage)
        try:
            frozen = chain.capture(0.0)
        finally:
            chain.release()
        diagnostics = planning.plan_diagnostics(BINDING, planner.plan(frozen, SETTINGS, CONTEXT))
        # The origins are read from the frozen snapshot, not the changed live source.
        stage.RemovePrim("/World/ZCopiesA")
        assert planning.plan_diagnostics(BINDING, planner.plan(frozen, SETTINGS, CONTEXT)) == diagnostics
    expected = {
        path: 1 for path, placeholder in unsupported.placeholders.items() if placeholder.type_name == "BasisCurves"
    } | dict.fromkeys(subjects, 5)
    reports = [d for d in diagnostics if d.code is DiagnosticCode.UNTRANSLATED_TYPE and "BasisCurves" in d.message]
    assert len(reports) == len(expected), reports
    assert {d.source_path for d in reports} == expected.keys()
    for report in reports:
        count = expected[report.source_path]
        assert (f"{count} drawn copies" in report.message) if count > 1 else "drawn copies" not in report.message


def test_nested_point_copies_of_a_prototype_child_are_reported_with_its_definition(tmp_path: Path) -> None:
    # The mesh is a child of one instancer's prototype root, and that instancer is itself a prototype of another.
    with evaluation.transforms(tmp_path) as transforms:
        stage = transforms.projective_stage
        mesh = stage.GetPrimAtPath(transforms.projective_mesh_path)
        UsdGeom.Xformable(mesh.GetParent()).ClearXformOpOrder()
        UsdGeom.Xformable(mesh).AddTransformOp().Set(transforms.projective_world_matrix)
        other = stage.DefinePrim("/World/OtherProjective")
        other.GetReferences().AddInternalReference(mesh.GetPath())
        subjects = [transforms.projective_mesh_path, str(other.GetPath())]
        for name in ("ZCopiesA", "ZCopiesB"):
            instancer = UsdGeom.PointInstancer.Define(stage, f"/World/{name}")
            instancer.CreatePrototypesRel().SetTargets([str(mesh.GetParent().GetPath()), subjects[1]])
            instancer.CreateProtoIndicesAttr([0, 1, 0, 1])
            instancer.CreatePositionsAttr([(i * 2, 0, 0) for i in range(4)])
        outer = UsdGeom.PointInstancer.Define(stage, "/World/ZOuter")
        outer.CreatePrototypesRel().SetTargets(["/World/ZCopiesA"])
        outer.CreateProtoIndicesAttr([0, 0])
        outer.CreatePositionsAttr([(0, 0, 0), (2, 0, 0)])

        chain = planner.SceneIndexChain(stage)
        try:
            frozen = chain.capture(0.0)
        finally:
            chain.release()
    diagnostics = planning.plan_diagnostics(BINDING, planner.plan(frozen, SETTINGS, CONTEXT))
    reports = [d for d in diagnostics if d.code is DiagnosticCode.PROJECTIVE_TRANSFORM]
    # The fixture's two native copies are a third, distinct definition.
    assert {d.source_path for d in reports} == {*subjects, min(transforms.projective_instance_world_matrices)}
    # Each is drawn itself, twice by each instancer, and twice by each of ZOuter's two copies of ZCopiesA.
    assert all("9 drawn copies" in d.message for d in reports if d.source_path in subjects)
