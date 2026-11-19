"""The checks and behavior every node shares, on step 4's node types (docs/plans/cook-module.md steps 3 and 4).

The checks against each node's definition, muting, and each node's cache, with Layer from File and Stage Output as the
nodes. Expected values come from the plan's "Node types in C++" and the note's "The tree as plain data".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Sdf, Usd

import proscenium_cook
from fixtures.scenes import Scene, copy_scene
from proscenium_cook import DiagnosticCode, Severity

if TYPE_CHECKING:
    from pathlib import Path


def _cook(tmp_path: Path, tree: str) -> proscenium_cook.CookResult:
    stage = Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / tree))
    return proscenium_cook.TreeCook(stage, base_directory=tmp_path).cook()


def _codes(result: proscenium_cook.CookResult, node_id: str) -> list[tuple[Severity, DiagnosticCode]]:
    report = result.node_reports.get(node_id)
    return [] if report is None else [(d.severity, d.code) for d in report.diagnostics]


@pytest.mark.parametrize(
    ("node_id", "code", "source_path"),
    [
        ("NewerVersion", DiagnosticCode.NEWER_NODE_VERSION, "/Tree/NewerVersion.node:version"),
        ("MissingVersion", DiagnosticCode.MISSING_NODE_VERSION, "/Tree/MissingVersion"),
        ("VersionWrongType", DiagnosticCode.WRONG_ATTRIBUTE_TYPE, "/Tree/VersionWrongType.node:version"),
        ("MuteWrongType", DiagnosticCode.WRONG_ATTRIBUTE_TYPE, "/Tree/MuteWrongType.node:mute"),
        ("UnknownAttribute", DiagnosticCode.UNKNOWN_ATTRIBUTE, "/Tree/UnknownAttribute.props:colour"),
        ("WrongAttributeType", DiagnosticCode.WRONG_ATTRIBUTE_TYPE, "/Tree/WrongAttributeType.props:path"),
        ("TooManyLinks", DiagnosticCode.TOO_MANY_LINKS, "/Tree/TooManyLinks.inputs:layer"),
    ],
)
def test_check_against_the_definition_is_one_error(
    tmp_path: Path, node_id: str, code: DiagnosticCode, source_path: str
) -> None:
    result = _cook(tmp_path, "node_checks.usda")
    assert _codes(result, node_id) == [(Severity.ERROR, code)]
    assert result.node_reports[node_id].diagnostics[0].source_path == source_path


def test_node_with_an_error_does_not_run(tmp_path: Path) -> None:
    result = _cook(tmp_path, "node_checks.usda")
    assert result.stage_outputs == {}  # TooManyLinks, the only Stage Output, has an error
    assert _codes(result, "Read") == [] and _codes(result, "ReadOther") == []


def test_muted_node_passes_nothing_without_a_pass_through(tmp_path: Path) -> None:
    result = _cook(tmp_path, "muting.usda")
    assert result.stage_outputs == {}  # ReadsMuted and ReadsBroken get no layer, and MutedOut doesn't run
    assert _codes(result, "MutedRead") == [] and _codes(result, "MutedOut") == []
    (warning,) = result.node_reports["ReadsMuted"].diagnostics
    assert (warning.code, warning.severity) == (DiagnosticCode.NO_UPSTREAM_VALUE, Severity.WARNING)
    assert '"MutedRead", which is muted' in warning.message


def test_muted_node_with_an_error_still_reports_it(tmp_path: Path) -> None:
    result = _cook(tmp_path, "muting.usda")
    assert _codes(result, "MutedBroken") == [(Severity.ERROR, DiagnosticCode.NEWER_NODE_VERSION)]
    assert _codes(result, "ReadsBroken") == [(Severity.WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)]


def test_node_cache_is_kept_by_id_and_type(tmp_path: Path) -> None:
    # Read's cache holds the layer it read, so the layer stays open between cooks only while the cache does.
    tree = Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / "cache.usda"))
    cook = proscenium_cook.TreeCook(tree, base_directory=tmp_path)
    base = str(tmp_path / "base.usda")
    cook.cook()
    cook.cook()
    assert Sdf.Layer.Find(base) is not None  # the same node, of the same type, keeps its cache
    tree.GetRootLayer().GetPrimAtPath("/Tree/Read").typeName = "StageOutput"  # a new node reusing the name
    cook.cook()
    assert Sdf.Layer.Find(base) is None
    tree.GetRootLayer().GetPrimAtPath("/Tree/Read").typeName = "LayerFromFile"
    cook.cook()
    assert Sdf.Layer.Find(base) is not None
    del tree.GetRootLayer().GetPrimAtPath("/Tree").nameChildren["Read"]  # a node gone from the tree drops its cache
    cook.cook()
    assert Sdf.Layer.Find(base) is None
