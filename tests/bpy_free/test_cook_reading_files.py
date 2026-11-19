"""Layer from File and Stage Output: a stage composed on a file the tree reads (docs/plans/cook-module.md step 4).

Expected values come from the note's sections for each node (docs/phase3/node-tree.md "Layer from File", "Stage
Output", and "The tree as plain data"), and from USD's own APIs on the returned stages.
"""

from __future__ import annotations

import gc
from pathlib import Path

import pytest
from pxr import Sdf, Usd, UsdGeom

import proscenium_cook
from fixtures.scenes import Scene, copy_scene
from proscenium_cook import DiagnosticCode, Severity


def _open_tree(tmp_path: Path, tree: str) -> Usd.Stage:
    return Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / tree))


def _cook(tmp_path: Path, tree: str) -> proscenium_cook.CookResult:
    return proscenium_cook.TreeCook(_open_tree(tmp_path, tree), base_directory=tmp_path).cook()


def _codes(result: proscenium_cook.CookResult, node_id: str) -> list[tuple[Severity, DiagnosticCode]]:
    report = result.node_reports.get(node_id)
    return [] if report is None else [(d.severity, d.code) for d in report.diagnostics]


def test_stage_output_composes_the_read_layer_with_payloads_loaded(tmp_path: Path) -> None:
    result = _cook(tmp_path, "stage_outputs.usda")
    stage = result.stage_outputs["Out"]
    assert Path(stage.GetRootLayer().identifier) == tmp_path / "base.usda"  # USD writes / on Windows too
    assert stage.GetPrimAtPath("/World/Chair/Seat").IsValid()  # only in base.usda's payload
    for node_id in ("Read", "Out", "Shared"):
        assert _codes(result, node_id) == [], node_id


def test_two_stage_outputs_on_one_layer_share_it(tmp_path: Path) -> None:
    result = _cook(tmp_path, "stage_outputs.usda")
    assert result.stage_outputs["Shared"].GetRootLayer() == result.stage_outputs["Out"].GetRootLayer()


def test_root_layer_without_metrics_warns_and_falls_back(tmp_path: Path) -> None:
    result = _cook(tmp_path, "stage_outputs.usda")
    assert _codes(result, "Bare") == [(Severity.WARNING, DiagnosticCode.MISSING_STAGE_METRICS)]
    (warning,) = result.node_reports["Bare"].diagnostics
    assert "upAxis" in warning.message and "metersPerUnit" in warning.message
    # The stage still composes, at USD's fallbacks, though its sublayer authors Z-up in meters.
    stage = result.stage_outputs["Bare"]
    assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y
    assert UsdGeom.GetStageMetersPerUnit(stage) == pytest.approx(0.01)


def test_unlinked_stage_output_has_no_stage(tmp_path: Path) -> None:
    result = _cook(tmp_path, "stage_outputs.usda")
    assert set(result.stage_outputs) == {"Out", "Shared", "Bare"}
    (warning,) = result.node_reports["Unlinked"].diagnostics
    assert (warning.severity, warning.code) == (Severity.WARNING, DiagnosticCode.UNLINKED_INPUT)
    assert warning.source_path == "/Tree/Unlinked.inputs:layer"


def test_returned_stage_outlives_the_cook(tmp_path: Path) -> None:
    cook = proscenium_cook.TreeCook(_open_tree(tmp_path, "stage_outputs.usda"), base_directory=tmp_path)
    stage = cook.cook().stage_outputs["Out"]
    del cook
    gc.collect()
    assert stage.GetPrimAtPath("/World/Chair/Seat").IsValid()


def test_stage_output_keeps_its_stage_while_its_root_layer_stays(tmp_path: Path) -> None:
    # A binding reuses its evaluation stage only while the source stage's root and session layers stay the same, and
    # tools author in the session layer (docs/spec/source-access.md "Source Stages").
    tree = _open_tree(tmp_path, "stage_outputs.usda")
    cook = proscenium_cook.TreeCook(tree, base_directory=tmp_path)
    first = cook.cook().stage_outputs["Out"]
    Sdf.CreatePrimInLayer(first.GetSessionLayer(), "/World/SessionEdit")
    second = cook.cook().stage_outputs["Out"]
    assert second == first
    assert second.GetPrimAtPath("/World/SessionEdit").IsValid()
    tree.GetRootLayer().GetAttributeAtPath("/Tree/Read.props:path").default = "//other.usda"
    third = cook.cook().stage_outputs["Out"]
    assert third != first
    assert Path(third.GetRootLayer().identifier) == tmp_path / "other.usda"


def test_layer_from_file_reads_the_process_shared_copy(tmp_path: Path) -> None:
    cook = proscenium_cook.TreeCook(_open_tree(tmp_path, "stage_outputs.usda"), base_directory=tmp_path)
    cook.cook()
    # Another tool's unsaved edit to the open layer shows in the next cook's stage.
    layer = Sdf.Layer.Find(str(tmp_path / "base.usda"))
    Sdf.CreatePrimInLayer(layer, "/World/Edited")
    del layer
    assert cook.cook().stage_outputs["Out"].GetPrimAtPath("/World/Edited").IsValid()


def test_path_problems_are_the_nodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # so WorkingDirectory's ./ path finds base.usda, and only warns
    tree = _open_tree(tmp_path, "paths.usda")
    as_written = tree.GetRootLayer().GetAttributeAtPath("/Tree/AsWritten.props:path")
    as_written.default = str(tmp_path / "other.usda")  # an absolute path, to the resolver as written
    result = proscenium_cook.TreeCook(tree, base_directory=tmp_path).cook()
    assert _codes(result, "Based") == []
    assert _codes(result, "AsWritten") == []
    expected = {
        "WorkingDirectory": (Severity.WARNING, DiagnosticCode.WORKING_DIRECTORY_PATH),
        "Empty": (Severity.ERROR, DiagnosticCode.MISSING_PATH),
        "Missing": (Severity.ERROR, DiagnosticCode.FILE_NOT_FOUND),
        "Unreadable": (Severity.ERROR, DiagnosticCode.UNREADABLE_FILE),
    }
    for node_id, code in expected.items():
        assert _codes(result, node_id) == [code], node_id
        assert result.node_reports[node_id].diagnostics[0].source_path == f"/Tree/{node_id}.props:path"


def test_link_from_a_failed_node_warns_once_naming_it(tmp_path: Path) -> None:
    result = _cook(tmp_path, "paths.usda")
    assert _codes(result, "Consumer") == [(Severity.WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)]  # not Missing's error
    (warning,) = result.node_reports["Consumer"].diagnostics
    assert '"Missing"' in warning.message
    assert warning.source_path == "/Tree/Consumer.inputs:layer"
    assert "Consumer" not in result.stage_outputs


def test_base_directory_path_without_one_asks_to_save(tmp_path: Path) -> None:
    result = proscenium_cook.TreeCook(_open_tree(tmp_path, "paths.usda")).cook()
    for node_id in ("Based", "Missing", "Unreadable"):
        assert _codes(result, node_id) == [(Severity.ERROR, DiagnosticCode.MISSING_BASE_DIRECTORY)], node_id
        assert "save the .blend" in result.node_reports[node_id].diagnostics[0].message
