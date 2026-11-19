"""The Viewer on a Layer: the stage the editor's UI shows (docs/plans/cook-module.md step 5).

Expected values come from the note's Viewer (docs/phase3/node-tree.md "Viewer"), the plan's Output, and USD's own APIs
on the returned stages.
"""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf, Usd

import proscenium_cook
from fixtures.scenes import Scene, copy_scene
from proscenium_cook import DiagnosticCode, Severity


def _open_tree(tmp_path: Path) -> Usd.Stage:
    return Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / "viewers.usda"))


def _cook(tmp_path: Path) -> proscenium_cook.CookResult:
    return proscenium_cook.TreeCook(_open_tree(tmp_path), base_directory=tmp_path).cook()


def test_viewer_composes_its_layer_with_payloads_loaded(tmp_path: Path) -> None:
    result = _cook(tmp_path)
    stage = result.viewer_stages["View"]
    assert Path(stage.GetRootLayer().identifier) == tmp_path / "base.usda"  # USD writes / on Windows too
    assert stage.GetPrimAtPath("/World/Chair/Seat").IsValid()  # only in base.usda's payload
    assert "View" not in result.node_reports


def test_viewer_and_stage_output_share_their_layer(tmp_path: Path) -> None:
    result = _cook(tmp_path)
    assert result.viewer_stages["View"].GetRootLayer() == result.stage_outputs["Out"].GetRootLayer()
    assert set(result.stage_outputs) == {"Out"}  # a Viewer's stage isn't a Stage Output's


def test_context_does_nothing_on_a_layer_from_file(tmp_path: Path) -> None:
    # A Layer from File's layer has no context, so both stages hold the layer alone.
    result = _cook(tmp_path)
    for node_id in ("View", "ContextOff"):
        stage = result.viewer_stages[node_id]
        assert stage.GetLayerStack(includeSessionLayers=False) == [stage.GetRootLayer()], node_id
    assert "ContextOff" not in result.node_reports


def test_viewer_does_not_warn_of_missing_metrics(tmp_path: Path) -> None:
    # Its stage feeds no binding, so it isn't converted, and the root layer's metrics don't matter to it.
    result = _cook(tmp_path)
    assert Path(result.viewer_stages["BareView"].GetRootLayer().identifier) == tmp_path / "no_metrics.usda"
    assert "BareView" not in result.node_reports


def test_viewer_with_no_layer_has_no_stage(tmp_path: Path) -> None:
    result = _cook(tmp_path)
    assert set(result.viewer_stages) == {"View", "ContextOff", "BareView"}
    assert "Unlinked" not in result.node_reports  # the editor shows there's nothing to view
    (warning,) = result.node_reports["FromMissing"].diagnostics
    assert (warning.severity, warning.code) == (Severity.WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)
    assert '"Missing"' in warning.message


def test_viewer_keeps_its_stage_while_its_root_layer_stays(tmp_path: Path) -> None:
    tree = _open_tree(tmp_path)
    cook = proscenium_cook.TreeCook(tree, base_directory=tmp_path)
    first = cook.cook().viewer_stages["View"]
    Sdf.CreatePrimInLayer(first.GetSessionLayer(), "/World/SessionEdit")
    second = cook.cook().viewer_stages["View"]
    assert second == first
    assert second.GetPrimAtPath("/World/SessionEdit").IsValid()
    tree.GetRootLayer().GetAttributeAtPath("/Tree/Read.props:path").default = "//other.usda"
    third = cook.cook().viewer_stages["View"]
    assert third != first
    assert Path(third.GetRootLayer().identifier) == tmp_path / "other.usda"
