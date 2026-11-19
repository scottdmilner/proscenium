"""TreeCook on malformed trees: each problem is a diagnostic, never an exception (docs/plans/cook-module.md step 3).

The trees' nodes are Relay or Scope, which are no node types, where a test needs only the tree's structure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Usd

import proscenium_cook
from fixtures.scenes import Scene, copy_scene
from proscenium_cook import DiagnosticCode, Severity

if TYPE_CHECKING:
    from pathlib import Path


def _cook(tmp_path: Path, tree: str) -> proscenium_cook.CookResult:
    stage = Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / tree))
    return proscenium_cook.TreeCook(stage, base_directory=tmp_path).cook()


def _codes(diagnostics: tuple[proscenium_cook.NodeDiagnostic, ...]) -> list[DiagnosticCode]:
    return [diagnostic.code for diagnostic in diagnostics]


def test_empty_tree_cooks_to_an_empty_result(tmp_path: Path) -> None:
    result = _cook(tmp_path, "empty_tree.usda")
    assert result == proscenium_cook.CookResult({}, {}, {}, ())


@pytest.mark.parametrize(
    ("tree", "code"),
    [
        ("missing_tree.usda", DiagnosticCode.MISSING_TREE),
        ("not_a_node_tree.usda", DiagnosticCode.NOT_A_NODE_TREE),
        ("newer_tree_format.usda", DiagnosticCode.UNKNOWN_TREE_FORMAT),
        ("missing_tree_format.usda", DiagnosticCode.UNKNOWN_TREE_FORMAT),
    ],
)
def test_unreadable_tree_has_one_tree_error_and_no_nodes(tmp_path: Path, tree: str, code: DiagnosticCode) -> None:
    result = _cook(tmp_path, tree)
    assert _codes(result.tree_diagnostics) == [code]
    assert result.tree_diagnostics[0].severity == Severity.ERROR
    assert result.node_reports == {}  # the nodes of a tree the cook can't read aren't read
    assert result.stage_outputs == {} and result.viewer_stages == {}


def test_sublayer_and_arc_are_tree_errors(tmp_path: Path) -> None:
    result = _cook(tmp_path, "composition_in_tree.usda")
    errors = [(d.code, d.source_path) for d in result.tree_diagnostics]
    assert errors == [
        (DiagnosticCode.COMPOSITION_IN_TREE, "/"),
        (DiagnosticCode.COMPOSITION_IN_TREE, "/Tree/Referencing"),
    ]
    assert _codes(result.node_reports["Referencing"].diagnostics) == [DiagnosticCode.UNKNOWN_NODE_TYPE]


def test_prim_names_decode_to_node_ids(tmp_path: Path) -> None:
    result = _cook(tmp_path, "node_names.usda")
    # The note's examples, each decoded exactly; Relay is no node type, so each node has a report.
    assert set(result.node_reports) == {"Set Attribute", "N.001", "1st", "Größe", "a😀b", "_2e_"}
    assert result.node_reports["Set Attribute"].diagnostics[0].source_path == "/Tree/Set_20_Attribute"
    invalid = [(d.code, d.source_path) for d in result.tree_diagnostics]
    assert invalid == [
        (DiagnosticCode.INVALID_NODE_NAME, "/Tree/Bad_zz_Name"),
        (DiagnosticCode.INVALID_NODE_NAME, "/Tree/_41_"),
    ]


def test_unknown_node_type_is_the_nodes_error(tmp_path: Path) -> None:
    report = _cook(tmp_path, "node_names.usda").node_reports["Set Attribute"]
    (diagnostic,) = report.diagnostics
    assert (diagnostic.severity, diagnostic.code) == (Severity.ERROR, DiagnosticCode.UNKNOWN_NODE_TYPE)
    assert "Relay" in diagnostic.message
    assert report.report_data == {}


def test_connection_to_no_output_is_unresolved(tmp_path: Path) -> None:
    reports = _cook(tmp_path, "unresolved_connections.usda").node_reports
    for node_id, input_path in [
        ("Missing", "/Tree/Missing.inputs:layer"),
        ("ToInput", "/Tree/ToInput.inputs:layer"),
        ("FromProperty", "/Tree/FromProperty.props:layer"),
    ]:
        unresolved = [d for d in reports[node_id].diagnostics if d.code == DiagnosticCode.UNRESOLVED_CONNECTION]
        assert [d.source_path for d in unresolved] == [input_path], node_id
    assert "Source" not in reports  # it reads base.usda, and its output isn't what the others' connections name


def test_nodes_on_a_cycle_get_its_error(tmp_path: Path) -> None:
    reports = _cook(tmp_path, "cycle.usda").node_reports
    on_cycle = {node_id for node_id, report in reports.items() if DiagnosticCode.CYCLE in _codes(report.diagnostics)}
    assert on_cycle == {"A", "B"}  # C, downstream of the cycle, and D, apart from it, aren't on it


def test_each_cook_reads_the_tree_again(tmp_path: Path) -> None:
    stage = Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / "empty_tree.usda"))
    cook = proscenium_cook.TreeCook(stage)
    assert cook.cook().node_reports == {}
    stage.GetRootLayer().GetPrimAtPath("/Tree").typeName = "Xform"  # the caller changes its tree
    assert _codes(cook.cook().tree_diagnostics) == [DiagnosticCode.NOT_A_NODE_TREE]


def test_no_stage_is_misuse() -> None:
    with pytest.raises(ValueError, match="stage"):
        proscenium_cook.TreeCook(None)  # ty: ignore[invalid-argument-type]
