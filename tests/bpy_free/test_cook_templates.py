"""A New Layer Zone's Template: its copy, its anchored paths, and their write table (cook-module.md step 7).

Expected values come from the note's sections on Templates and files (docs/phase3/node-tree.md "New Layer Zone",
"Provenance", and "Writing"), and from USD's own APIs: the Template's own stage, and Sdf's anchoring of each authored
path to the Template's file.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pxr import Sdf, Usd

import proscenium_cook
from fixtures.scenes import Scene, copy_scene
from proscenium_cook import DiagnosticCode, Severity

if TYPE_CHECKING:
    from collections.abc import Callable

ERROR, WARNING = Severity.ERROR, Severity.WARNING
TEXTURES = ("wood.png", "a.png", "b.png", "f1.png", "f2.png")
TIMES = (Usd.TimeCode.Default(), 0.0, 1.0, 2.0)


def _tree(tmp_path: Path, tree: str) -> proscenium_cook.TreeCook:
    directory = copy_scene(Scene.COOK_TREES, tmp_path)
    (directory / "templates" / "textures").mkdir()
    for texture in TEXTURES:
        (directory / "templates" / "textures" / texture).touch()
    return proscenium_cook.TreeCook(Usd.Stage.Open(str(directory / tree)), base_directory=tmp_path)


def _codes(result: proscenium_cook.CookResult, node_id: str) -> list[tuple[Severity, DiagnosticCode]]:
    report = result.node_reports.get(node_id)
    return [] if report is None else [(d.severity, d.code) for d in report.diagnostics]


def _template(tmp_path: Path) -> Sdf.Layer:
    return Sdf.Layer.FindOrOpen(str(tmp_path / "templates" / "template.usda"))


def _anchored(tmp_path: Path, authored: str) -> str:
    return Sdf.ComputeAssetPathRelativeToLayer(_template(tmp_path), authored)


def _copy_stage(tmp_path: Path) -> Usd.Stage:
    return _tree(tmp_path, "templates.usda").cook().stage_outputs["CopyOut"]


def _asset_values(stage: Usd.Stage) -> dict[tuple[str, Any], list[str]]:
    """Each asset value's resolved path or paths, by attribute path and time."""
    values: dict[tuple[str, Any], list[str]] = {}
    for prim in stage.Traverse():
        for attribute in prim.GetAttributes():
            for time in TIMES:
                value = attribute.Get(time)
                if isinstance(value, Sdf.AssetPath):
                    values[str(attribute.GetPath()), time] = [value.resolvedPath]
                elif attribute.GetTypeName() == Sdf.ValueTypeNames.AssetArray and value is not None:
                    values[str(attribute.GetPath()), time] = [path.resolvedPath for path in value]
    return values


def test_copy_composes_as_its_template_does(tmp_path: Path) -> None:
    result = _tree(tmp_path, "templates.usda").cook()
    copy = result.stage_outputs["CopyOut"]
    template = Usd.Stage.Open(_template(tmp_path))
    assert [p.GetPath() for p in copy.Traverse()] == [p.GetPath() for p in template.Traverse()]
    # pxr's stubs lack GetCompositionErrors, which USD 0.26 binds.
    assert copy.GetCompositionErrors() == []  # ty: ignore[unresolved-attribute]
    assert template.GetCompositionErrors() == []  # ty: ignore[unresolved-attribute]
    values = _asset_values(copy)
    assert values == _asset_values(template)
    # Every texture resolves, and the <UDIM> path resolves on neither stage, since a UDIM path resolves per tile.
    resolved = {path for paths in values.values() for path in paths if path}
    assert {Path(path).name for path in resolved} == set(TEXTURES)
    assert values["/World/Shader.inputs:tiles", Usd.TimeCode.Default()] == [""]
    # The clip's value shows only if the clip and its manifest resolve.
    assert copy.GetAttributeAtPath("/World/Clipped.size").Get(0) == 7
    for node_id in ("Source", "Copy", "CopyEnd", "CopyOut"):
        assert _codes(result, node_id) == [], node_id


# Each place a relative path can live in the Template (docs/phase3/node-tree.md "New Layer Zone"), read from a layer.
PLACES: list[tuple[str, Callable[[Sdf.Layer], Any], Any]] = [
    # pxr's stubs don't make a list proxy iterable, which it is.
    ("sublayer", lambda layer: list(layer.subLayerPaths), ["./sub.usda"]),  # ty: ignore[invalid-argument-type]
    ("customLayerData", lambda layer: layer.customLayerData["notes"].path, "./notes.txt"),
    ("assetInfo", lambda layer: layer.GetPrimAtPath("/World").assetInfo["identifier"].path, "./world.usda"),
    ("customData", lambda layer: layer.GetPrimAtPath("/World").customData["source"].path, "../source.blend"),
    (
        "reference",
        lambda layer: [r.assetPath for r in layer.GetPrimAtPath("/World/Referenced").referenceList.prependedItems],
        ["./ref.usda"],
    ),
    (
        "bare payload",
        lambda layer: [p.assetPath for p in layer.GetPrimAtPath("/World/Payloaded").payloadList.prependedItems],
        ["prop.usda"],
    ),
    (
        "reference in a variant",
        lambda layer: [
            r.assetPath for r in layer.GetPrimAtPath("/World/Looks{look=red}Inner").referenceList.prependedItems
        ],
        ["./variants/inner.usda"],
    ),
    ("asset", lambda layer: layer.GetAttributeAtPath("/World/Shader.inputs:file").default.path, "./textures/wood.png"),
    (
        "asset[]",
        lambda layer: [p.path for p in layer.GetAttributeAtPath("/World/Shader.inputs:files").default],
        ["./textures/a.png", "./textures/b.png"],
    ),
    (
        "time samples",
        lambda layer: [layer.QueryTimeSample("/World/Shader.inputs:animated", t).path for t in (1.0, 2.0)],
        ["./textures/f1.png", "./textures/f2.png"],
    ),
    (
        "<UDIM>",
        lambda layer: layer.GetAttributeAtPath("/World/Shader.inputs:tiles").default.path,
        "./textures/tile.<UDIM>.png",
    ),
    (
        "clips' assetPaths",
        lambda layer: [p.path for p in layer.GetPrimAtPath("/World/Clipped").GetInfo("clips")["default"]["assetPaths"]],
        ["./clips/clip.usda"],
    ),
    (
        "clips' manifestAssetPath",
        lambda layer: layer.GetPrimAtPath("/World/Clipped").GetInfo("clips")["default"]["manifestAssetPath"].path,
        "./clips/manifest.usda",
    ),
]


@pytest.mark.parametrize(("place", "read", "authored"), PLACES, ids=[place for place, _, _ in PLACES])
def test_each_relative_path_is_anchored_to_the_templates_file(
    tmp_path: Path, place: str, read: Callable[[Sdf.Layer], Any], authored: Any
) -> None:
    stage = _copy_stage(tmp_path)  # it holds its root layer, which its cook's zone kept
    layer = stage.GetRootLayer()
    assert read(_template(tmp_path)) == authored, place
    expected = (
        [_anchored(tmp_path, a) for a in authored] if isinstance(authored, list) else _anchored(tmp_path, authored)
    )
    assert read(layer) == expected
    assert expected != authored


def test_absolute_path_is_left_as_authored(tmp_path: Path) -> None:
    stage = _copy_stage(tmp_path)  # it holds its root layer, which its cook's zone kept
    layer = stage.GetRootLayer()
    assert layer.GetAttributeAtPath("/World/Shader.inputs:absolute").default.path == "/absolute/never.png"


def test_copy_holds_the_templates_prims_and_layer_metadata(tmp_path: Path) -> None:
    stage = _copy_stage(tmp_path)  # it holds its root layer, which its cook's zone kept
    layer = stage.GetRootLayer()
    template = _template(tmp_path)
    assert layer.anonymous
    for field in ("defaultPrim", "upAxis", "metersPerUnit"):
        assert layer.pseudoRoot.GetInfo(field) == template.pseudoRoot.GetInfo(field), field
    assert list(layer.rootPrims.keys()) == list(template.rootPrims.keys())


def test_begin_reports_each_anchored_path_with_its_authored_form(tmp_path: Path) -> None:
    result = _tree(tmp_path, "templates.usda").cook()
    authored = []
    for _, _, value in PLACES:
        authored.extend(value if isinstance(value, list) else [value])
    expected = {_anchored(tmp_path, path): path for path in authored}
    assert len(expected) == len(authored)  # no two authored paths anchor to one string
    assert result.node_reports["Copy"].report_data["anchoredPaths"] == expected


def test_zone_from_another_zone_copies_its_layer_and_write_table(tmp_path: Path) -> None:
    result = _tree(tmp_path, "templates.usda").cook()
    copy = result.stage_outputs["CopyOut"].GetRootLayer()
    again = result.stage_outputs["AgainOut"].GetRootLayer()
    # Again's ID sorts before Copy's, so had its task run first it would have started empty.
    assert again != copy
    assert again.ExportToString() == copy.ExportToString()
    again_paths = result.node_reports["Again"].report_data["anchoredPaths"]
    assert again_paths == result.node_reports["Copy"].report_data["anchoredPaths"]
    for node_id in ("Again", "AgainEnd", "AgainOut"):
        assert _codes(result, node_id) == [], node_id


def test_zone_follows_its_template_across_cooks(tmp_path: Path) -> None:
    cook = _tree(tmp_path, "templates.usda")
    first = cook.cook().stage_outputs["CopyOut"]
    # The Template is read live: Layer from File keeps the process's shared copy, which this edits.
    Sdf.CreatePrimInLayer(_template(tmp_path), "/Added")
    second = cook.cook().stage_outputs["CopyOut"]
    assert second == first
    assert second.GetPrimAtPath("/Added").IsValid()


def test_template_that_brings_nothing_stops_the_zone(tmp_path: Path) -> None:
    result = _tree(tmp_path, "templates.usda").cook()
    assert _codes(result, "Absent") == [(ERROR, DiagnosticCode.FILE_NOT_FOUND)]
    (warning,) = result.node_reports["Missing"].diagnostics
    assert (warning.severity, warning.code) == (WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)
    assert '"Absent"' in warning.message
    assert warning.source_path == "/Tree/Missing.inputs:template"
    assert "anchoredPaths" not in result.node_reports["Missing"].report_data
    # An empty layer never stands in for the Template's: the zone gives nothing out, and its end names its begin.
    (stopped,) = result.node_reports["MissingEnd"].diagnostics
    assert (stopped.severity, stopped.code) == (WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)
    assert '"Missing"' in stopped.message
    assert "MissingOut" not in result.stage_outputs


def test_zone_whose_template_is_its_own_file_is_an_error_on_both(tmp_path: Path) -> None:
    result = _tree(tmp_path, "zone_file_readers.usda").cook()
    own = str(tmp_path / "own.usda")
    for node_id, other, attribute in (("Own", "OwnFile", "inputs:file"), ("OwnFile", "Own", "props:path")):
        (error,) = result.node_reports[node_id].diagnostics
        assert (error.severity, error.code) == (ERROR, DiagnosticCode.SHARED_FILE)
        assert error.source_path == f"/Tree/{node_id}.{attribute}"
        assert own in error.message and f'"{other}"' in error.message
    # The begin's error stops its zone, and a Layer from File with the error doesn't read its file.
    assert _codes(result, "OwnEnd") == [(WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)]
    assert _codes(result, "OwnOut") == [(WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)]
    assert "OwnOut" not in result.stage_outputs


def test_layer_from_file_reading_a_zones_file_is_an_error_on_both(tmp_path: Path) -> None:
    result = _tree(tmp_path, "zone_file_readers.usda").cook()
    assert _codes(result, "Reader") == [(ERROR, DiagnosticCode.SHARED_FILE)]
    assert _codes(result, "Other") == [(ERROR, DiagnosticCode.SHARED_FILE)]
    assert '"Other"' in result.node_reports["Reader"].diagnostics[0].message


def test_relative_spellings_of_one_file_are_shared(tmp_path: Path) -> None:
    # Bare's relative_zone.usda and RelativeZone's ./relative_zone.usda both name the file in the working directory.
    result = _tree(tmp_path, "zone_file_readers.usda").cook()
    assert (ERROR, DiagnosticCode.SHARED_FILE) in _codes(result, "Bare")
    assert (ERROR, DiagnosticCode.SHARED_FILE) in _codes(result, "RelativeZone")


def test_two_layer_from_files_may_read_one_file(tmp_path: Path) -> None:
    result = _tree(tmp_path, "zone_file_readers.usda").cook()
    assert _codes(result, "ReaderA") == []
    assert _codes(result, "ReaderB") == []
