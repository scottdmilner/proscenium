"""New Layer Zone: a zone's chain, its task, its layer, and its file (docs/plans/cook-module.md step 6).

Expected values come from the note's sections on zones (docs/phase3/node-tree.md "What a zone holds", "Cooking the
layers", "Diagnostics", "Writing", and "New Layer Zone"), and from USD's own APIs on the returned stages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Ar, Sdf, Usd

import proscenium_cook
from fixtures.scenes import Scene, copy_scene
from proscenium_cook import DiagnosticCode, Severity

if TYPE_CHECKING:
    from pathlib import Path

ERROR, WARNING = Severity.ERROR, Severity.WARNING


def _open_tree(tmp_path: Path, tree: str) -> Usd.Stage:
    return Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / tree))


def _cook(tmp_path: Path, tree: str) -> proscenium_cook.CookResult:
    return proscenium_cook.TreeCook(_open_tree(tmp_path, tree), base_directory=tmp_path).cook()


def _codes(result: proscenium_cook.CookResult, node_id: str) -> list[tuple[Severity, DiagnosticCode]]:
    report = result.node_reports.get(node_id)
    return [] if report is None else [(d.severity, d.code) for d in report.diagnostics]


def test_empty_zone_gives_its_stage_output_an_anonymous_layer(tmp_path: Path) -> None:
    result = _cook(tmp_path, "new_layer_zones.usda")
    stage = result.stage_outputs["Out"]
    root = stage.GetRootLayer()
    assert root.anonymous
    assert list(root.rootPrims) == []
    assert list(stage.GetPseudoRoot().GetAllChildren()) == []
    # The zone authors no metrics until Configure Layer, step 14, so the Stage Output warns of them.
    assert _codes(result, "Out") == [(WARNING, DiagnosticCode.MISSING_STAGE_METRICS)]
    for node_id in ("Zone", "ZoneEnd", "View", "Spare", "SpareEnd"):
        assert _codes(result, node_id) == [], node_id


def test_stage_output_and_viewer_share_the_zones_layer(tmp_path: Path) -> None:
    cook = proscenium_cook.TreeCook(_open_tree(tmp_path, "new_layer_zones.usda"), base_directory=tmp_path)
    result = cook.cook("View")
    assert result.viewer_stage is not None
    assert result.viewer_stage.GetRootLayer() == result.stage_outputs["Out"].GetRootLayer()


def test_zones_are_cooked_into_the_layers_they_keep(tmp_path: Path) -> None:
    cook = proscenium_cook.TreeCook(_open_tree(tmp_path, "new_layer_zones.usda"), base_directory=tmp_path)
    first = cook.cook().stage_outputs["Out"]
    layer = first.GetRootLayer()
    Sdf.CreatePrimInLayer(layer, "/Stray")  # content the zone's chain didn't author
    second = cook.cook().stage_outputs["Out"]
    # The same layer, so the same stage, with the zone's content moved into it in place of what it held.
    assert second == first
    assert second.GetRootLayer().identifier == layer.identifier
    assert not second.GetPrimAtPath("/Stray").IsValid()


@pytest.mark.parametrize(
    ("node_id", "expected", "source_path"),
    [
        ("Branch", [(ERROR, DiagnosticCode.CHAIN_BRANCH)], "/Tree/Branch.outputs:layer"),
        ("BranchEnd", [(ERROR, DiagnosticCode.BROKEN_CHAIN)], "/Tree/BranchEnd.inputs:layer"),
        ("Other", [], None),
        ("OtherEnd", [(ERROR, DiagnosticCode.BROKEN_CHAIN)], "/Tree/OtherEnd.inputs:layer"),
        ("Dead", [], None),
        ("DeadEnd", [(ERROR, DiagnosticCode.BROKEN_CHAIN)], "/Tree/DeadEnd.inputs:layer"),
        ("CrossA", [], None),
        ("CrossAEnd", [(ERROR, DiagnosticCode.MISMATCHED_ZONE)], "/Tree/CrossAEnd.inputs:layer"),
        ("CrossB", [], None),
        ("CrossBEnd", [(ERROR, DiagnosticCode.MISMATCHED_ZONE)], "/Tree/CrossBEnd.inputs:layer"),
        ("Lone", [(ERROR, DiagnosticCode.UNPAIRED_ZONE)], "/Tree/Lone"),
        ("LoneEnd", [(ERROR, DiagnosticCode.UNPAIRED_ZONE)], "/Tree/LoneEnd"),
        ("Wrong", [(ERROR, DiagnosticCode.UNPAIRED_ZONE)], "/Tree/Wrong.zone:end"),
        ("TwinA", [(ERROR, DiagnosticCode.UNPAIRED_ZONE)], "/Tree/TwinA.zone:end"),
        ("TwinB", [(ERROR, DiagnosticCode.UNPAIRED_ZONE)], "/Tree/TwinB.zone:end"),
        ("TwinEnd", [(ERROR, DiagnosticCode.UNPAIRED_ZONE)], "/Tree/TwinEnd"),
        ("NotABegin", [(ERROR, DiagnosticCode.UNKNOWN_ATTRIBUTE)], "/Tree/NotABegin.zone:end"),
    ],
)
def test_chain_error_is_on_the_node_it_concerns(
    tmp_path: Path, node_id: str, expected: list[tuple[Severity, DiagnosticCode]], source_path: str | None
) -> None:
    result = _cook(tmp_path, "zone_chains.usda")
    assert _codes(result, node_id) == expected
    if source_path is not None:
        assert result.node_reports[node_id].diagnostics[0].source_path == source_path


def test_broken_chain_names_its_begin_and_gives_nothing_out(tmp_path: Path) -> None:
    result = _cook(tmp_path, "zone_chains.usda")
    assert '"Dead"' in result.node_reports["DeadEnd"].diagnostics[0].message
    assert '"CrossB"' in result.node_reports["CrossAEnd"].diagnostics[0].message
    (warning,) = result.node_reports["DeadOut"].diagnostics
    assert (warning.severity, warning.code) == (WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)
    assert '"DeadEnd"' in warning.message
    assert result.stage_outputs == {}


def test_two_zones_with_one_file_are_each_an_error_that_stops_the_zone(tmp_path: Path) -> None:
    result = _cook(tmp_path, "zone_files.usda")
    for node_id, other in (("First", "Second"), ("Second", "First")):
        (error,) = result.node_reports[node_id].diagnostics
        assert (error.severity, error.code) == (ERROR, DiagnosticCode.SHARED_FILE)
        assert error.source_path == f"/Tree/{node_id}.inputs:file"
        # The file as the resolver identifies a new file, with / on Windows too.
        shared = Ar.GetResolver().CreateIdentifierForNewAsset(str(tmp_path / "shared.usda"))
        assert shared in error.message and f'"{other}"' in error.message
        (warning,) = result.node_reports[f"{node_id}End"].diagnostics
        assert (warning.severity, warning.code) == (WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)
        assert f'"{node_id}"' in warning.message
    assert _codes(result, "FirstOut") == [(WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)]
    assert set(result.stage_outputs) == {"ThirdOut", "NoFileOut"}


def _ignores_case(directory: Path) -> bool:
    (directory / "case_probe").touch()
    return (directory / "CASE_PROBE").exists()


def test_one_file_in_another_case_is_shared_where_the_file_system_ignores_case(tmp_path: Path) -> None:
    result = _cook(tmp_path, "zone_file_spellings.usda")
    expected = [(ERROR, DiagnosticCode.SHARED_FILE)] if _ignores_case(tmp_path) else []
    assert _codes(result, "Upper") == expected
    assert _codes(result, "Lower") == expected


def test_one_file_through_a_symlink_is_shared(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    try:
        (tmp_path / "linked").symlink_to(tmp_path / "real", target_is_directory=True)
    except OSError:
        pytest.skip("this account can't make symlinks")  # Windows without Developer Mode
    result = _cook(tmp_path, "zone_file_spellings.usda")
    for node_id in ("Linked", "Direct"):
        assert _codes(result, node_id) == [(ERROR, DiagnosticCode.SHARED_FILE)], node_id


def test_zones_with_no_file_share_none(tmp_path: Path) -> None:
    result = _cook(tmp_path, "zone_files.usda")
    for node_id in ("Third", "ThirdEnd", "NoFile", "NoFileEnd", "NoFileToo", "NoFileTooEnd"):
        assert _codes(result, node_id) == [], node_id


def test_muted_begin_stops_its_zone(tmp_path: Path) -> None:
    result = _cook(tmp_path, "zone_files.usda")
    assert _codes(result, "Muted") == []
    (warning,) = result.node_reports["MutedEnd"].diagnostics
    assert (warning.severity, warning.code) == (WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)
    assert '"Muted", which is muted' in warning.message
    assert "MutedOut" not in result.stage_outputs


def test_zone_file_relative_to_the_blend_without_one_stops_the_zone(tmp_path: Path) -> None:
    result = proscenium_cook.TreeCook(_open_tree(tmp_path, "zone_files.usda")).cook()
    for node_id in ("First", "Second", "Third"):
        assert _codes(result, node_id) == [(ERROR, DiagnosticCode.MISSING_BASE_DIRECTORY)], node_id
    assert set(result.stage_outputs) == {"NoFileOut"}
