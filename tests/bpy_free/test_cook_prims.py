"""Prim and Create Prim, and a chain that authors (docs/plans/cook-module.md step 8).

Expected values come from the note's sections on these nodes and on chains (docs/phase3/node-tree.md "Prim", "Create
Prim", "New Layer Zone", "What a zone holds", "Diagnostics", and "Provenance"), and from USD's own APIs on the
returned stages and on the Template's layer.
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

ERROR, WARNING = Severity.ERROR, Severity.WARNING


def _tree(tmp_path: Path, tree: str) -> proscenium_cook.TreeCook:
    stage = Usd.Stage.Open(str(copy_scene(Scene.COOK_TREES, tmp_path) / tree))
    return proscenium_cook.TreeCook(stage, base_directory=tmp_path)


def _cook(tmp_path: Path, tree: str) -> proscenium_cook.CookResult:
    return _tree(tmp_path, tree).cook()


def _codes(result: proscenium_cook.CookResult, node_id: str) -> list[tuple[Severity, DiagnosticCode]]:
    report = result.node_reports.get(node_id)
    return [] if report is None else [(d.severity, d.code) for d in report.diagnostics]


def _only(result: proscenium_cook.CookResult, node_id: str) -> proscenium_cook.NodeDiagnostic:
    (diagnostic,) = result.node_reports[node_id].diagnostics
    return diagnostic


def _prim_specs(result: proscenium_cook.CookResult, begin: str) -> dict[str, str]:
    return dict(result.node_reports[begin].report_data["primSpecs"])


def _layer_fields(result: proscenium_cook.CookResult, begin: str) -> dict[str, str]:
    return dict(result.node_reports[begin].report_data["layerFields"])


def _template_fields(tmp_path: Path) -> list[str]:
    # The Template's own layer metadata fields, as Sdf lists them.
    layer = Sdf.Layer.FindOrOpen(str(tmp_path / "templates" / "template.usda"))  # held while its spec is read
    return list(layer.pseudoRoot.ListInfoKeys())


def _template_prim_paths(tmp_path: Path) -> list[str]:
    # Every prim spec the Template's own layer holds, a spec inside a variant at its path there.
    layer = Sdf.Layer.FindOrOpen(str(tmp_path / "templates" / "template.usda"))
    paths: list[str] = []

    def visit(path: Sdf.Path | str) -> None:
        if Sdf.Path(path).IsPrimPath():
            paths.append(str(path))

    layer.Traverse(Sdf.Path.absoluteRootPath, visit)
    return paths


# Create Prim's spec, its ancestors' overs, and its Prim output


def test_create_prim_authors_each_spec_with_its_specifier_and_type(tmp_path: Path) -> None:
    stage = _cook(tmp_path, "create_prims.usda").stage_outputs["Out"]  # it holds its root layer
    layer = stage.GetRootLayer()
    expected = {
        "/World": (Sdf.SpecifierDef, "Xform"),
        "/World/Chair": (Sdf.SpecifierDef, "Mesh"),  # under World's Prim output
        "/Set": (Sdf.SpecifierDef, "Xform"),  # Lamp's over for a missing ancestor, which Set takes
        "/Set/Room": (Sdf.SpecifierOver, ""),  # Lamp's other missing ancestor
        "/Set/Room/Lamp": (Sdf.SpecifierDef, ""),
        "/Base": (Sdf.SpecifierClass, ""),
        "/Over": (Sdf.SpecifierOver, ""),
    }
    for path, (specifier, type_name) in expected.items():
        spec = layer.GetPrimAtPath(Sdf.Path(path))
        assert spec is not None, path
        assert (spec.specifier, spec.typeName) == (specifier, type_name), path
    # Sdf keeps root prims in the order the chain created them, so /Set stays where Lamp's over put it.
    assert list(layer.rootPrims.keys()) == ["World", "Set", "Base", "Over"]


def test_end_authors_its_default_prim_from_a_create_prims_prim(tmp_path: Path) -> None:
    result = _cook(tmp_path, "create_prims.usda")
    assert result.stage_outputs["Out"].GetRootLayer().defaultPrim == "World"
    # Annex's end has no Default Prim and its zone no Template, so its layer has none.
    assert not result.stage_outputs["AnnexOut"].GetRootLayer().HasDefaultPrim()


def test_prim_from_another_zone_is_ready_before_either_task_runs(tmp_path: Path) -> None:
    result = _cook(tmp_path, "create_prims.usda")
    layer = result.stage_outputs["AnnexOut"].GetRootLayer()
    assert layer.GetPrimAtPath(Sdf.Path("/World/Chair/Extra")).specifier == Sdf.SpecifierDef
    assert layer.GetPrimAtPath(Sdf.Path("/World")).specifier == Sdf.SpecifierOver
    assert layer.GetPrimAtPath(Sdf.Path("/World/Chair")).specifier == Sdf.SpecifierOver
    for node_id in "Zone World Chair Lamp Base Over Set ZoneEnd Room Annex Extra AnnexEnd".split():
        assert _codes(result, node_id) == [], node_id


def test_edit_table_gives_each_spec_to_the_node_that_wrote_it(tmp_path: Path) -> None:
    result = _cook(tmp_path, "create_prims.usda")
    assert _prim_specs(result, "Zone") == {
        "/World": "World",
        "/World/Chair": "Chair",
        "/Set": "Set",  # the node that took the implicit over Lamp needed
        "/Set/Room": "Lamp",  # an implicit over is the node's that needed it
        "/Set/Room/Lamp": "Lamp",
        "/Base": "Base",
        "/Over": "Over",
    }
    assert _prim_specs(result, "Annex") == {"/World": "Extra", "/World/Chair": "Extra", "/World/Chair/Extra": "Extra"}
    # The end's defaultPrim is the end's; Annex's layer holds no metadata.
    assert _layer_fields(result, "Zone") == {"defaultPrim": "ZoneEnd"}
    assert "layerFields" not in result.node_reports["Annex"].report_data


def test_same_tree_cooks_to_the_same_layer(tmp_path: Path) -> None:
    first, second = (_cook(tmp_path, "create_prims.usda").stage_outputs["Out"] for _ in range(2))
    assert first.GetRootLayer() != second.GetRootLayer()
    assert first.GetRootLayer().ExportToString() == second.GetRootLayer().ExportToString()


# Template content in the edit table, and the Default Prim against it


def test_template_content_is_the_begins_in_the_edit_table(tmp_path: Path) -> None:
    result = _cook(tmp_path, "default_prims.usda")
    paths = _template_prim_paths(tmp_path)
    assert "/World/Looks{look=red}Inner" in paths
    assert _prim_specs(result, "Kept") == dict.fromkeys(paths, "Kept")
    assert _prim_specs(result, "Replaced") == {**dict.fromkeys(paths, "Replaced"), "/Stage": "Stage"}
    fields = _template_fields(tmp_path)
    assert "defaultPrim" in fields
    assert _layer_fields(result, "Kept") == dict.fromkeys(fields, "Kept")
    assert _layer_fields(result, "Replaced") == {**dict.fromkeys(fields, "Replaced"), "defaultPrim": "ReplacedEnd"}


def test_default_prim_keeps_the_templates_or_replaces_it(tmp_path: Path) -> None:
    result = _cook(tmp_path, "default_prims.usda")
    template = Sdf.Layer.FindOrOpen(str(tmp_path / "templates" / "template.usda"))
    assert result.stage_outputs["KeptOut"].GetRootLayer().defaultPrim == template.defaultPrim == "World"
    assert result.stage_outputs["ReplacedOut"].GetRootLayer().defaultPrim == "Stage"


def test_default_prim_below_the_root_is_authored_as_its_path(tmp_path: Path) -> None:
    result = _cook(tmp_path, "default_prims.usda")
    stage = result.stage_outputs["NestedOut"]
    # The pxr stubs predate USD 0.25's GetDefaultPrimAsPath.
    root = stage.GetRootLayer()
    assert root.GetDefaultPrimAsPath() == Sdf.Path("/Root/Child")  # ty: ignore[unresolved-attribute]
    assert stage.GetDefaultPrim().GetPath() == Sdf.Path("/Root/Child")
    assert _codes(result, "NestedEnd") == []
    assert _layer_fields(result, "Nested") == {"defaultPrim": "NestedEnd"}


def test_default_prim_that_isnt_a_prim_of_the_layer_stops_the_zone(tmp_path: Path) -> None:
    result = _cook(tmp_path, "default_prims.usda")
    error = _only(result, "NowhereEnd")
    assert (error.severity, error.code) == (ERROR, DiagnosticCode.INVALID_DEFAULT_PRIM)
    assert error.source_path == "/Tree/NowhereEnd.inputs:defaultPrim"
    assert "NowhereOut" not in result.stage_outputs
    assert '"NowhereEnd"' in _only(result, "NowhereOut").message


def test_default_prim_of_the_layers_root_is_an_error(tmp_path: Path) -> None:
    result = _cook(tmp_path, "default_prims.usda")
    error = _only(result, "PseudoEnd")
    assert (error.severity, error.code) == (ERROR, DiagnosticCode.INVALID_DEFAULT_PRIM)
    assert error.source_path == "/Tree/PseudoEnd.inputs:defaultPrim"
    assert "PseudoOut" not in result.stage_outputs


@pytest.mark.parametrize(("zone", "path"), [("Overed", "/Ghost"), ("Classed", "/Kind")])
def test_default_prim_that_isnt_a_def_warns_and_is_authored(tmp_path: Path, zone: str, path: str) -> None:
    result = _cook(tmp_path, "default_prims.usda")
    warning = _only(result, f"{zone}End")
    assert (warning.severity, warning.code) == (WARNING, DiagnosticCode.DEFAULT_PRIM_NOT_DEF)
    assert warning.source_path == f"/Tree/{zone}End.inputs:defaultPrim"
    stage = result.stage_outputs[f"{zone}Out"]
    assert stage.GetDefaultPrim().GetPath() == Sdf.Path(path)


def test_default_prim_link_that_brings_nothing_stops_the_zone(tmp_path: Path) -> None:
    result = _cook(tmp_path, "default_prims.usda")
    assert _codes(result, "NoPath") == [(ERROR, DiagnosticCode.MISSING_PATH)]
    warning = _only(result, "StarvedEnd")
    assert (warning.severity, warning.code) == (WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)
    assert '"NoPath"' in warning.message
    assert warning.source_path == "/Tree/StarvedEnd.inputs:defaultPrim"
    assert "StarvedOut" not in result.stage_outputs


# Create Prim's reports


@pytest.mark.parametrize(
    ("node_id", "author"),
    [
        ("Again", 'copied from the Template by "Copy"'),  # /World, from templates/template.usda
        ("Second", 'authored by "First"'),
        ("Outer", 'authored by "Patch"'),  # /Y, an over Patch created on purpose
    ],
)
def test_prim_the_layer_already_has_a_spec_for_is_an_error_naming_its_author(
    tmp_path: Path, node_id: str, author: str
) -> None:
    error = _only(_cook(tmp_path, "create_prim_errors.usda"), node_id)
    assert (error.severity, error.code) == (ERROR, DiagnosticCode.EXISTING_PRIM_SPEC)
    assert author in error.message
    assert error.source_path == f"/Tree/{node_id}.inputs:name"


def test_create_prim_with_an_error_stops_its_chain(tmp_path: Path) -> None:
    result = _cook(tmp_path, "create_prim_errors.usda")
    # After, past Again, doesn't run, so it reports nothing, and the zone gives nothing out.
    assert "After" not in result.node_reports
    stoppers = {
        "CopyEnd": "Again",
        "TwiceEnd": "Second",
        "OversEnd": "Outer",
        "NamesEnd": "Digit",
        "UnnamedEnd": "Blank",
        "OrphanEnd": "Parentless",
    }
    for end, stopper in stoppers.items():
        warning = _only(result, end)
        assert (warning.severity, warning.code) == (WARNING, DiagnosticCode.NO_UPSTREAM_VALUE), end
        assert f'"{stopper}"' in warning.message, end
    assert set(result.stage_outputs) == {"TypedOut"}


@pytest.mark.parametrize(
    ("node_id", "code", "source_path"),
    [
        ("Digit", DiagnosticCode.INVALID_PRIM_NAME, "/Tree/Digit.inputs:name"),
        ("Blank", DiagnosticCode.INVALID_PRIM_NAME, "/Tree/Blank.inputs:name"),
        ("Parentless", DiagnosticCode.INVALID_PRIM_PATH, "/Tree/Parentless.inputs:parent"),
        # A specifier's menu is closed: USD takes no other value.
        ("Odd", DiagnosticCode.INVALID_TOKEN, "/Tree/Odd.props:specifier"),
    ],
)
def test_name_parent_or_specifier_that_names_no_prim_is_an_error(
    tmp_path: Path, node_id: str, code: DiagnosticCode, source_path: str
) -> None:
    error = _only(_cook(tmp_path, "create_prim_errors.usda"), node_id)
    assert (error.severity, error.code, error.source_path) == (ERROR, code, source_path)


def test_node_the_chain_stops_before_reports_nothing_of_its_own(tmp_path: Path) -> None:
    # Unreached's empty Name is found with its Prim output, before any task, but held until its chain reaches it,
    # which it doesn't: Digit stops it first.
    result = _cook(tmp_path, "create_prim_errors.usda")
    assert _codes(result, "Unreached") == []
    assert _codes(result, "Digit") == [(ERROR, DiagnosticCode.INVALID_PRIM_NAME)]


@pytest.mark.parametrize(
    ("node_id", "code", "kind"),
    [
        ("Bogus", DiagnosticCode.UNKNOWN_PRIM_TYPE, None),  # NotAType
        ("Abstract", DiagnosticCode.NON_CONCRETE_PRIM_TYPE, Usd.SchemaKind.AbstractTyped),  # Gprim
        ("Api", DiagnosticCode.NON_CONCRETE_PRIM_TYPE, Usd.SchemaKind.MultipleApplyAPI),  # CollectionAPI
    ],
)
def test_type_that_isnt_a_concrete_schema_warns_and_is_authored(
    tmp_path: Path, node_id: str, code: DiagnosticCode, kind: Usd.SchemaKind | None
) -> None:
    result = _cook(tmp_path, "create_prim_errors.usda")
    stage = result.stage_outputs["TypedOut"]  # it holds its root layer
    type_name = stage.GetRootLayer().GetPrimAtPath(Sdf.Path(f"/{node_id}")).typeName
    # The registry's own kind for the type, so the warning matches what USD says it is.
    schema = Usd.SchemaRegistry.GetTypeFromSchemaTypeName(type_name)
    assert (None if schema.isUnknown else Usd.SchemaRegistry.GetSchemaKind(schema)) == kind
    warning = _only(result, node_id)
    assert (warning.severity, warning.code) == (WARNING, code)
    assert warning.source_path == f"/Tree/{node_id}.props:type"


# Prim's path checks, and its Prim into a Layer


@pytest.mark.parametrize("node_id", ["Relative", "Property", "Variant", "Garbage", "Unanchored"])
def test_prim_that_isnt_an_absolute_prim_path_is_an_error(tmp_path: Path, node_id: str) -> None:
    error = _only(_cook(tmp_path, "prim_paths.usda"), node_id)
    assert (error.severity, error.code) == (ERROR, DiagnosticCode.INVALID_PRIM_PATH)


def test_prim_with_an_empty_path_is_an_error_and_absolute_paths_are_not(tmp_path: Path) -> None:
    result = _cook(tmp_path, "prim_paths.usda")
    assert _codes(result, "Empty") == [(ERROR, DiagnosticCode.MISSING_PATH)]
    assert _codes(result, "Root") == []
    assert _codes(result, "Good") == []


def test_prim_into_a_layer_input_is_an_incompatible_link(tmp_path: Path) -> None:
    result = _cook(tmp_path, "prim_paths.usda")
    error = _only(result, "PrimIntoLayer")
    assert (error.severity, error.code) == (ERROR, DiagnosticCode.INCOMPATIBLE_LINK)
    assert error.source_path == "/Tree/PrimIntoLayer.inputs:layer"
    assert result.stage_outputs == {}


# Chains with Create Prims


def test_create_prim_in_no_chain_is_an_error_and_the_nodes_after_it_report_nothing(tmp_path: Path) -> None:
    result = _cook(tmp_path, "chain_errors.usda")
    error = _only(result, "Loose")
    assert (error.severity, error.code) == (ERROR, DiagnosticCode.NO_CHAIN)
    assert "LooseNext" not in result.node_reports


def test_nodes_after_a_branch_report_nothing(tmp_path: Path) -> None:
    result = _cook(tmp_path, "chain_errors.usda")
    assert _codes(result, "Split") == [
        (ERROR, DiagnosticCode.CHAIN_BRANCH),
        (WARNING, DiagnosticCode.UNREACHED_ZONE_END),
    ]
    for node_id in ("Left", "Right", "LeftNext"):
        assert node_id not in result.node_reports, node_id
    assert _codes(result, "ForkEnd") == [(ERROR, DiagnosticCode.BROKEN_CHAIN)]


def test_broken_chains_nodes_warn_their_edits_never_reach_its_end(tmp_path: Path) -> None:
    result = _cook(tmp_path, "chain_errors.usda")
    warning = _only(result, "Stray")
    assert (warning.severity, warning.code) == (WARNING, DiagnosticCode.UNREACHED_ZONE_END)
    assert '"BrokenEnd"' in warning.message


def test_muted_create_prim_passes_its_editable_layer_through_also_with_an_error(tmp_path: Path) -> None:
    result = _cook(tmp_path, "chain_errors.usda")
    assert "Hushed" not in result.node_reports
    assert _codes(result, "Newer") == [(ERROR, DiagnosticCode.NEWER_NODE_VERSION)]
    layer = result.stage_outputs["QuietOut"].GetRootLayer()
    assert list(layer.rootPrims.keys()) == ["Kept"]
    assert _prim_specs(result, "Quiet") == {"/Kept": "Kept"}
    assert _codes(result, "QuietEnd") == []


def test_muted_create_prims_prim_brings_nothing(tmp_path: Path) -> None:
    # It has no pass-through, so a node using it warns, rather than editing the muted node's Parent.
    result = _cook(tmp_path, "chain_errors.usda")
    warning = _only(result, "Echo")
    assert (warning.severity, warning.code) == (WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)
    assert '"Hushed", which is muted' in warning.message
    assert '"Echo"' in _only(result, "EchoesEnd").message


def test_link_through_muted_create_prims_to_a_failed_node_warns_once_naming_it(tmp_path: Path) -> None:
    result = _cook(tmp_path, "chain_errors.usda")
    assert _codes(result, "Bad") == [(ERROR, DiagnosticCode.INVALID_PRIM_NAME)]
    warning = _only(result, "FailEnd")
    assert (warning.severity, warning.code) == (WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)
    assert '"Bad"' in warning.message
    for node_id in ("MuteA", "MuteB"):
        assert node_id not in result.node_reports, node_id


def test_chain_node_whose_link_brings_nothing_stops_its_chain(tmp_path: Path) -> None:
    result = _cook(tmp_path, "chain_errors.usda")
    warning = _only(result, "Hungry")
    assert (warning.severity, warning.code) == (WARNING, DiagnosticCode.NO_UPSTREAM_VALUE)
    assert '"NoPath"' in warning.message
    assert warning.source_path == "/Tree/Hungry.inputs:parent"
    assert '"Hungry"' in _only(result, "StarvedEnd").message
