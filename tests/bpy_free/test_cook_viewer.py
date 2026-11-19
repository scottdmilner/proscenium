"""The Viewer: the stage the editor's UI shows, on a Layer and partway down a chain (plan steps 5 and 8).

The plan is docs/plans/cook-module.md. Expected values come from the note's Viewer (docs/phase3/node-tree.md "Viewer"),
the plan's Output, and USD's own APIs on the returned stages. Each cook names the one Viewer it cooks, so a fixture
holds several, one for each case.
"""

from __future__ import annotations

import gc
from pathlib import Path

import pytest
from pxr import Sdf, Usd

import proscenium_cook
from fixtures.scenes import Scene, copy_scene
from proscenium_cook import DiagnosticCode, Severity


def _open_tree(tmp_path: Path) -> Usd.Stage:
    return Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / "viewers.usda"))


def _cook(tmp_path: Path, viewer: str | None) -> proscenium_cook.CookResult:
    return proscenium_cook.TreeCook(_open_tree(tmp_path), base_directory=tmp_path).cook(viewer)


def _viewed(result: proscenium_cook.CookResult) -> Usd.Stage:
    assert result.viewer_stage is not None
    return result.viewer_stage


def test_viewer_composes_its_layer_with_payloads_loaded(tmp_path: Path) -> None:
    result = _cook(tmp_path, "View")
    stage = _viewed(result)
    assert Path(stage.GetRootLayer().identifier) == tmp_path / "base.usda"  # USD writes / on Windows too
    assert stage.GetPrimAtPath("/World/Chair/Seat").IsValid()  # only in base.usda's payload
    assert "View" not in result.node_reports


def test_viewer_and_stage_output_share_their_layer(tmp_path: Path) -> None:
    result = _cook(tmp_path, "View")
    assert _viewed(result).GetRootLayer() == result.stage_outputs["Out"].GetRootLayer()
    assert set(result.stage_outputs) == {"Out"}  # a Viewer's stage isn't a Stage Output's


@pytest.mark.parametrize("viewer", ["View", "ContextOff"])
def test_context_does_nothing_on_a_layer_from_file(tmp_path: Path, viewer: str) -> None:
    # A Layer from File's layer has no context, so the stage holds the layer alone, with Context on or off.
    result = _cook(tmp_path, viewer)
    stage = _viewed(result)
    assert stage.GetLayerStack(includeSessionLayers=False) == [stage.GetRootLayer()]
    assert viewer not in result.node_reports


def test_viewer_does_not_warn_of_missing_metrics(tmp_path: Path) -> None:
    # Its stage feeds no binding, so it isn't converted, and the root layer's metrics don't matter to it.
    result = _cook(tmp_path, "BareView")
    assert Path(_viewed(result).GetRootLayer().identifier) == tmp_path / "no_metrics.usda"
    assert "BareView" not in result.node_reports


def test_viewer_with_no_layer_has_no_stage(tmp_path: Path) -> None:
    result = _cook(tmp_path, "Unlinked")
    assert result.viewer_stage is None
    assert "Unlinked" not in result.node_reports  # the editor shows there's nothing to view
    result = _cook(tmp_path, "FromMissing")
    assert result.viewer_stage is None
    (warning,) = result.node_reports["FromMissing"].diagnostics
    assert (warning.severity, warning.code) == (Severity.WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)
    assert '"Missing"' in warning.message


def test_viewer_keeps_its_stage_while_its_root_layer_stays(tmp_path: Path) -> None:
    tree = _open_tree(tmp_path)
    cook = proscenium_cook.TreeCook(tree, base_directory=tmp_path)
    first = _viewed(cook.cook("View"))
    Sdf.CreatePrimInLayer(first.GetSessionLayer(), "/World/SessionEdit")
    second = _viewed(cook.cook("View"))
    assert second == first
    assert second.GetPrimAtPath("/World/SessionEdit").IsValid()
    tree.GetRootLayer().GetAttributeAtPath("/Tree/Read.props:path").default = "//other.usda"
    third = _viewed(cook.cook("View"))
    assert third != first
    assert Path(third.GetRootLayer().identifier) == tmp_path / "other.usda"


# One Viewer at a time


def test_only_the_active_viewer_runs(tmp_path: Path) -> None:
    # FromMissing's link brings nothing, which it warns of only when it runs.
    result = _cook(tmp_path, "View")
    assert "FromMissing" not in result.node_reports
    result = _cook(tmp_path, None)
    assert result.viewer_stage is None
    assert "FromMissing" not in result.node_reports
    assert set(result.stage_outputs) == {"Out"}  # every other task still runs


@pytest.mark.parametrize("viewer", ["Nobody", "Out"])
def test_active_viewer_that_names_no_viewer_warns_and_cooks_no_viewer(tmp_path: Path, viewer: str) -> None:
    # Nobody names no node, as a deleted Viewer's ID would, and Out names a Stage Output, as a retyped one's would.
    result = _cook(tmp_path, viewer)
    (warning,) = result.tree_diagnostics
    assert (warning.severity, warning.code) == (Severity.WARNING, DiagnosticCode.UNKNOWN_VIEWER)
    assert f'"{viewer}"' in warning.message
    assert result.viewer_stage is None
    assert set(result.stage_outputs) == {"Out"}  # the rest of the tree still cooks


def test_active_viewer_on_an_unreadable_tree_warns_too(tmp_path: Path) -> None:
    stage = Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / "missing_tree.usda"))
    result = proscenium_cook.TreeCook(stage, base_directory=tmp_path).cook("View")
    codes = [diagnostic.code for diagnostic in result.tree_diagnostics]
    assert codes == [DiagnosticCode.MISSING_TREE, DiagnosticCode.UNKNOWN_VIEWER]


# Partway down a chain


def _chain_tree(tmp_path: Path) -> proscenium_cook.TreeCook:
    stage = Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / "chain_viewers.usda"))
    return proscenium_cook.TreeCook(stage, base_directory=tmp_path)


def _root_prims(stage: Usd.Stage) -> list[str]:
    return list(stage.GetRootLayer().rootPrims.keys())


@pytest.mark.parametrize(("viewer", "prims"), [("AtBegin", []), ("AtA", ["A"]), ("AtEnd", ["A", "B"])])
def test_viewer_partway_down_a_chain_shows_the_layer_as_the_chain_left_it_there(
    tmp_path: Path, viewer: str, prims: list[str]
) -> None:
    result = _chain_tree(tmp_path).cook(viewer)
    assert _root_prims(_viewed(result)) == prims
    # The nodes after it still run.
    assert _root_prims(result.stage_outputs["Out"]) == ["A", "B"]


def test_viewers_copy_is_its_own_and_its_ends_is_the_zones_layer(tmp_path: Path) -> None:
    cook = _chain_tree(tmp_path)
    result = cook.cook("AtA")
    zone_layer = result.stage_outputs["Out"].GetRootLayer()
    copy = _viewed(result).GetRootLayer()
    assert copy != zone_layer
    assert copy.anonymous
    # A muted node passes its Editable Layer through, so a Viewer on it sees the copy made at the node before it.
    assert _viewed(cook.cook("AtMuted")).GetRootLayer() == copy
    assert _viewed(cook.cook("AtEnd")).GetRootLayer() == zone_layer


@pytest.mark.parametrize("viewer", [None, "AtBegin", "AtA", "AtMuted", "AtEnd"])
def test_viewer_link_doesnt_branch_the_chain(tmp_path: Path, viewer: str | None) -> None:
    result = _chain_tree(tmp_path).cook(viewer)
    for node_id in ("Zone", "A", "Muted", "B", "ZoneEnd", "AtBegin", "AtA", "AtMuted", "AtEnd"):
        assert result.node_reports.get(node_id) is None or not result.node_reports[node_id].diagnostics, node_id


def test_only_a_viewer_takes_an_editable_layer(tmp_path: Path) -> None:
    result = _chain_tree(tmp_path).cook()
    (error,) = result.node_reports["NotViewer"].diagnostics
    assert (error.severity, error.code) == (Severity.ERROR, DiagnosticCode.INCOMPATIBLE_LINK)
    assert "NotViewer" not in result.stage_outputs


def test_viewer_past_where_the_chain_stops_gets_nothing(tmp_path: Path) -> None:
    cook = _chain_tree(tmp_path)
    assert _root_prims(_viewed(cook.cook("AtFine"))) == ["F"]
    result = cook.cook("AtFails")
    assert result.viewer_stage is None
    (warning,) = result.node_reports["AtFails"].diagnostics
    assert (warning.severity, warning.code) == (Severity.WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)
    assert '"Fails"' in warning.message


def test_viewer_partway_down_a_chain_keeps_its_stage_across_cooks(tmp_path: Path) -> None:
    stage = Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / "chain_viewers.usda"))
    cook = proscenium_cook.TreeCook(stage, base_directory=tmp_path)
    first = _viewed(cook.cook("AtA"))
    # The zone cooks inside an SdfChangeBlock, and the Viewer's kept stage, which composes its copy, recomposes once it
    # closes, so it shows the recook's content.
    stage.GetRootLayer().GetAttributeAtPath("/Tree/A.inputs:name").default = "Renamed"
    second = _viewed(cook.cook("AtA"))
    assert second == first
    assert _root_prims(second) == ["Renamed"]
    assert second.GetPrimAtPath("/Renamed").IsValid()
    assert not second.GetPrimAtPath("/A").IsValid()


def _is_alive(identifier: str) -> bool:
    # Whether any holder keeps the layer: the cook's caches, or a stage composing it. The Layer Find returns is dropped.
    gc.collect()
    return bool(Sdf.Layer.Find(identifier))


@pytest.mark.parametrize("next_viewer", ["AtBegin", "AtEnd", None])
def test_switching_away_drops_the_viewers_stage_and_copy(tmp_path: Path, next_viewer: str | None) -> None:
    # AtA's copy of A's layer is its stage's root, so the copy outlives neither the cache that keeps it nor the stage
    # that composes it. Once another Viewer, or none, is active, A keeps no copy and AtA no stage, and none is made.
    cook = _chain_tree(tmp_path)
    copy = _viewed(cook.cook("AtA")).GetRootLayer().identifier
    assert _is_alive(copy)
    cook.cook(next_viewer)
    assert not _is_alive(copy)


def test_active_viewer_that_wont_run_keeps_no_stage_or_copy(tmp_path: Path) -> None:
    # Muted, AtA doesn't run, so A makes no copy for it, and AtA drops the stage it composed before.
    stage = Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / "chain_viewers.usda"))
    cook = proscenium_cook.TreeCook(stage, base_directory=tmp_path)
    copy = _viewed(cook.cook("AtA")).GetRootLayer().identifier
    viewer = stage.GetRootLayer().GetPrimAtPath("/Tree/AtA")
    Sdf.AttributeSpec(viewer, "node:mute", Sdf.ValueTypeNames.Bool).default = True
    result = cook.cook("AtA")
    assert result.viewer_stage is None
    assert not _is_alive(copy)
