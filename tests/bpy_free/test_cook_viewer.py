"""The Viewer: the stage the editor's UI shows, on a Layer and partway down a chain (plan steps 5 and 8).

The plan is docs/plans/cook-module.md. Expected values come from the note's Viewer (docs/phase3/node-tree.md "Viewer"),
the plan's Output, and USD's own APIs on the returned stages.
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


# Partway down a chain


def _chain_tree(tmp_path: Path) -> proscenium_cook.TreeCook:
    stage = Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / "chain_viewers.usda"))
    return proscenium_cook.TreeCook(stage, base_directory=tmp_path)


def _root_prims(stage: Usd.Stage) -> list[str]:
    return list(stage.GetRootLayer().rootPrims.keys())


def test_viewer_partway_down_a_chain_shows_the_layer_as_the_chain_left_it_there(tmp_path: Path) -> None:
    result = _chain_tree(tmp_path).cook()
    viewers = result.viewer_stages
    assert _root_prims(viewers["AtBegin"]) == []
    assert _root_prims(viewers["AtA"]) == ["A"]
    # A muted node passes its Editable Layer through, so a Viewer on it sees what the node before it left.
    assert viewers["AtMuted"].GetRootLayer() == viewers["AtA"].GetRootLayer()
    assert _root_prims(viewers["AtEnd"]) == ["A", "B"]
    # Its copy is the Viewer's own, never the zone's layer, and the nodes after it still run.
    zone_layer = result.stage_outputs["Out"].GetRootLayer()
    assert viewers["AtA"].GetRootLayer() != zone_layer
    assert viewers["AtA"].GetRootLayer().anonymous
    assert viewers["AtEnd"].GetRootLayer() == zone_layer
    assert _root_prims(result.stage_outputs["Out"]) == ["A", "B"]


def test_viewer_link_doesnt_branch_the_chain(tmp_path: Path) -> None:
    result = _chain_tree(tmp_path).cook()
    for node_id in ("Zone", "A", "Muted", "B", "ZoneEnd", "AtBegin", "AtA", "AtMuted", "AtEnd"):
        assert result.node_reports.get(node_id) is None or not result.node_reports[node_id].diagnostics, node_id


def test_only_a_viewer_takes_an_editable_layer(tmp_path: Path) -> None:
    result = _chain_tree(tmp_path).cook()
    (error,) = result.node_reports["NotViewer"].diagnostics
    assert (error.severity, error.code) == (Severity.ERROR, DiagnosticCode.INCOMPATIBLE_LINK)
    assert "NotViewer" not in result.stage_outputs


def test_viewer_past_where_the_chain_stops_gets_nothing(tmp_path: Path) -> None:
    result = _chain_tree(tmp_path).cook()
    assert _root_prims(result.viewer_stages["AtFine"]) == ["F"]
    assert "AtFails" not in result.viewer_stages
    (warning,) = result.node_reports["AtFails"].diagnostics
    assert (warning.severity, warning.code) == (Severity.WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)
    assert '"Fails"' in warning.message


def test_viewer_partway_down_a_chain_keeps_its_stage_across_cooks(tmp_path: Path) -> None:
    stage = Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / "chain_viewers.usda"))
    cook = proscenium_cook.TreeCook(stage, base_directory=tmp_path)
    first = cook.cook().viewer_stages["AtA"]
    # The zone cooks inside an SdfChangeBlock, and the Viewer's kept stage, which composes its copy, recomposes once it
    # closes, so it shows the recook's content.
    stage.GetRootLayer().GetAttributeAtPath("/Tree/A.inputs:name").default = "Renamed"
    second = cook.cook().viewer_stages["AtA"]
    assert second == first
    assert _root_prims(second) == ["Renamed"]
    assert second.GetPrimAtPath("/Renamed").IsValid()
    assert not second.GetPrimAtPath("/A").IsValid()
