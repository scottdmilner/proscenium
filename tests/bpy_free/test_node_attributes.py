"""tools/node_attributes.py, the cook's attribute headers (docs/plans/cook-module.md "Node types in C++").

Each socket kind and value-type family becomes its C++ field, in the input struct or the output struct, the headers
compile with the cook's flags, and check catches a stale header.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

import native_build
import node_attributes
from blender_deps import current_platform
from fixtures.scenes import Scene, copy_scene

# Each input's field, from the plan's rules: a socket kind's own type, a value's C++ type (USD's, as Sdf names it,
# with a role sharing its stored type), AuthoredField for an optional field, and VtValue for a dynamic type.
EXPECTED_INPUTS = {
    "test_sockets_attributes.h": {
        "layer": "LayerInput",
        "sourceLayers": "std::vector<LayerInput>",
        "file": "FileInput",
        "prim": "PXR_NS::SdfPath",
        "prims": "PXR_NS::SdfPathExpression",
        "itemFile": "FileInput",  # inputs:item:file: later namespaces join in camel case
    },
    "test_values_attributes.h": {
        "boolValue": "bool",
        "ucharValue": "unsigned char",
        "intValue": "int",
        "uintValue": "unsigned int",
        "int64Value": "std::int64_t",
        "uint64Value": "std::uint64_t",
        "halfValue": "PXR_NS::GfHalf",
        "floatValue": "float",
        "doubleValue": "double",
        "timeCodeValue": "PXR_NS::SdfTimeCode",
        "stringValue": "std::string",
        "mode": "PXR_NS::TfToken",
        "assetValue": "PXR_NS::SdfAssetPath",
        "half2Value": "PXR_NS::GfVec2h",
        "float3Value": "PXR_NS::GfVec3f",
        "double4Value": "PXR_NS::GfVec4d",
        "int2Value": "PXR_NS::GfVec2i",
        "point3fValue": "PXR_NS::GfVec3f",
        "quathValue": "PXR_NS::GfQuath",
        "quatfValue": "PXR_NS::GfQuatf",
        "quatdValue": "PXR_NS::GfQuatd",
        "matrix2dValue": "PXR_NS::GfMatrix2d",
        "matrix3dValue": "PXR_NS::GfMatrix3d",
        "matrix4dValue": "PXR_NS::GfMatrix4d",
        "float3Array": "PXR_NS::VtArray<PXR_NS::GfVec3f>",
        "active": "AuthoredField<bool>",
        "kind": "AuthoredField<PXR_NS::TfToken>",
        "value": "PXR_NS::VtValue",
    },
    "test_no_inputs_attributes.h": {},
}

# Each output's field: a kind's own type, with a Layer's handle and a File's identifier held bare, and a value's or a
# dynamic type's as for an input.
EXPECTED_OUTPUTS = {
    "test_sockets_attributes.h": {
        "layer": "PXR_NS::SdfLayerHandle",
        "file": "std::string",
        "prim": "PXR_NS::SdfPath",
        "prims": "PXR_NS::SdfPathExpression",
    },
    "test_values_attributes.h": {"float3Value": "PXR_NS::GfVec3f", "value": "PXR_NS::VtValue"},
    "test_no_inputs_attributes.h": {"layer": "PXR_NS::SdfLayerHandle"},
}


@pytest.fixture
def definitions(tmp_path: Path) -> Path:
    return copy_scene(Scene.COOK_DEFINITIONS, tmp_path / "definitions") / "test_node_definitions.usda"


def _fields(header: str, struct: str) -> dict[str, str]:
    """The members of the struct ending in struct (Inputs or Outputs), by name: their declared types.

    An empty struct is on one line, and any other closes on a line of its own.
    """
    (body,) = re.findall(rf"^struct \w+{struct} \{{(?:\}};|(.*?)^\}};)$", header, flags=re.DOTALL | re.MULTILINE)
    return {name: cpp.strip() for cpp, name in re.findall(r"^\s*(.+?)\s+(\w+)\{\};", body, flags=re.MULTILINE)}


def test_each_kind_and_family_becomes_its_field(definitions: Path, tmp_path: Path) -> None:
    rendered = node_attributes.render(definitions, tmp_path)
    assert {path.name: _fields(text, "Inputs") for path, text in rendered.items()} == EXPECTED_INPUTS
    assert {path.name: _fields(text, "Outputs") for path, text in rendered.items()} == EXPECTED_OUTPUTS
    # The Editable Layer input and output are the context's.
    assert "editableLayer" not in rendered[tmp_path / "test_sockets_attributes.h"]


def test_structs_name_each_attribute(definitions: Path, tmp_path: Path) -> None:
    header = node_attributes.render(definitions, tmp_path)[tmp_path / "test_sockets_attributes.h"]
    assert 'static constexpr const char* kItemFile = "inputs:item:file";' in header
    assert 'static constexpr const char* kPrims = "outputs:prims";' in header


def test_writer_commits_each_output_as_a_linked_input_reads_it(definitions: Path, tmp_path: Path) -> None:
    # node_input_reader.h: a Layer input reads an SdfLayerHandle, and a File, Prim, or Prims input a string. An output
    # that holds nothing commits nothing; a value always commits.
    header = node_attributes.render(definitions, tmp_path)[tmp_path / "test_sockets_attributes.h"]
    assert "if (outputs.layer) {" in header
    assert 'values[PXR_NS::TfToken("outputs:layer")] = PXR_NS::VtValue(outputs.layer);' in header
    assert "if (!outputs.file.empty()) {" in header
    assert 'values[PXR_NS::TfToken("outputs:prim")] = PXR_NS::VtValue(outputs.prim.GetAsString());' in header
    assert 'values[PXR_NS::TfToken("outputs:prims")] = PXR_NS::VtValue(outputs.prims.GetText());' in header
    header = node_attributes.render(definitions, tmp_path)[tmp_path / "test_values_attributes.h"]
    assert "if (!outputs.value.IsEmpty()) {" in header
    line = 'values[PXR_NS::TfToken("outputs:float3Value")] = PXR_NS::VtValue(outputs.float3Value);'
    assert f"  ValueOutputs values;\n  {line}" in header


def test_reader_fills_each_field(definitions: Path, tmp_path: Path) -> None:
    header = node_attributes.render(definitions, tmp_path)[tmp_path / "test_sockets_attributes.h"]
    assert 'inputs.sourceLayers = reader.Layers("inputs:sourceLayers");' in header
    header = node_attributes.render(definitions, tmp_path)[tmp_path / "test_values_attributes.h"]
    assert 'inputs.active = reader.Optional<bool>("props:active");' in header
    assert 'inputs.value = reader.Dynamic("inputs:value");' in header
    assert 'inputs.float3Value = reader.Value<PXR_NS::GfVec3f>("props:float3Value");' in header


def test_check_finds_missing_stale_and_orphaned_headers(definitions: Path, tmp_path: Path) -> None:
    headers = tmp_path / "nodes"
    headers.mkdir()
    assert sorted(node_attributes.stale_headers(definitions, headers)) == [
        "test_no_inputs_attributes.h is missing",
        "test_sockets_attributes.h is missing",
        "test_values_attributes.h is missing",
    ]
    node_attributes.write_headers(definitions, headers)
    assert node_attributes.stale_headers(definitions, headers) == []
    (headers / "test_sockets_attributes.h").write_text("// edited by hand\n")
    (headers / "removed_type_attributes.h").write_text("// its definition is gone\n")
    (headers / "test_sockets.cpp").write_text("// a node's own source, which check and render leave alone\n")
    assert sorted(node_attributes.stale_headers(definitions, headers)) == [
        "removed_type_attributes.h has no definition",
        "test_sockets_attributes.h is out of date",
    ]
    node_attributes.write_headers(definitions, headers)
    assert sorted(p.name for p in headers.iterdir()) == sorted([*EXPECTED_INPUTS, "test_sockets.cpp"])


def test_shipped_headers_are_current() -> None:
    assert node_attributes.stale_headers(node_attributes.DEFINITIONS, node_attributes.HEADERS) == []


def _cook_compile_command() -> tuple[list[str], Path]:
    """The cook's build's command for python_bindings.cpp, as arguments, and the directory it runs in."""
    commands_path = native_build.COOK.cmake_dir / "compile_commands.json"
    if not commands_path.is_file():
        pytest.skip("the cook's build isn't configured here (tools/build_extension.py configures it)")
    for command in json.loads(commands_path.read_text(encoding="utf-8")):
        if Path(command["file"]).name == "python_bindings.cpp":
            arguments = command.get("arguments") or shlex.split(command["command"], posix=os.name != "nt")
            return arguments, Path(command["directory"])
    raise AssertionError(f"{commands_path} has no command for python_bindings.cpp")


def test_headers_compile_with_the_cooks_flags(definitions: Path, tmp_path: Path) -> None:
    arguments, directory = _cook_compile_command()
    if shutil.which(arguments[0]) is None:
        pytest.skip(f"{arguments[0]}, the cook's build's compiler, isn't on this machine (CI builds Linux's apart)")
    headers = tmp_path / "nodes"
    headers.mkdir()
    node_attributes.write_headers(definitions, headers)
    source = tmp_path / "includes_every_header.cpp"
    source.write_text("".join(f'#include "{p.as_posix()}"\n' for p in sorted(headers.iterdir())))
    msvc = Path(arguments[0]).stem.lower() == "cl"
    kept: list[str] = []
    skip_next = False
    for argument in arguments[1:]:
        if skip_next:
            skip_next = False
        elif argument == "-o":
            skip_next = True
        elif (
            argument in {"-c", "/c"} or argument.startswith(("/Fo", "-Fo")) or argument.endswith("python_bindings.cpp")
        ):
            continue
        else:
            kept.append(argument)
    command = [arguments[0], *kept, "/Zs" if msvc else "-fsyntax-only", str(source)]
    result = subprocess.run(
        command, cwd=directory, env=native_build.build_env(current_platform()), capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
