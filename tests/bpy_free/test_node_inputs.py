"""tools/node_inputs.py, the cook's input headers (docs/plans/cook-module.md "Node types in C++").

Each socket kind and value-type family becomes its C++ field, the headers compile with the cook's flags, and check
catches a stale header.
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
import node_inputs
from blender_deps import current_platform
from fixtures.scenes import Scene, copy_scene

# Each input's field, from the plan's rules: a socket kind's own type, a value's C++ type (USD's, as Sdf names it,
# with a role sharing its stored type), AuthoredField for an optional field, and VtValue for a dynamic type.
EXPECTED_FIELDS = {
    "test_sockets_inputs.h": {
        "layer": "LayerInput",
        "sourceLayers": "std::vector<LayerInput>",
        "file": "FileInput",
        "prim": "PXR_NS::SdfPath",
        "prims": "PXR_NS::SdfPathExpression",
        "itemFile": "FileInput",  # inputs:item:file: later namespaces join in camel case
    },
    "test_values_inputs.h": {
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
    "test_no_inputs_inputs.h": {},
}


@pytest.fixture
def definitions(tmp_path: Path) -> Path:
    return copy_scene(Scene.COOK_DEFINITIONS, tmp_path / "definitions") / "test_node_definitions.usda"


def _fields(header: str) -> dict[str, str]:
    """The input struct's members, by name: their declared types."""
    (body,) = re.findall(r"^struct \w+Inputs \{(.*?)\};$", header, flags=re.DOTALL | re.MULTILINE)
    return {name: cpp.strip() for cpp, name in re.findall(r"^\s*(.+?)\s+(\w+)\{\};", body, flags=re.MULTILINE)}


def test_each_kind_and_family_becomes_its_field(definitions: Path, tmp_path: Path) -> None:
    rendered = node_inputs.render(definitions, tmp_path)
    assert {path.name: _fields(text) for path, text in rendered.items()} == EXPECTED_FIELDS
    # The Editable Layer input is its context's, and outputs aren't inputs.
    assert "editableLayer" not in rendered[tmp_path / "test_sockets_inputs.h"]


def test_reader_fills_each_field(definitions: Path, tmp_path: Path) -> None:
    header = node_inputs.render(definitions, tmp_path)[tmp_path / "test_sockets_inputs.h"]
    assert 'inputs.sourceLayers = reader.Layers("inputs:sourceLayers");' in header
    header = node_inputs.render(definitions, tmp_path)[tmp_path / "test_values_inputs.h"]
    assert 'inputs.active = reader.Optional<bool>("props:active");' in header
    assert 'inputs.value = reader.Dynamic("inputs:value");' in header
    assert 'inputs.float3Value = reader.Value<PXR_NS::GfVec3f>("props:float3Value");' in header


def test_check_finds_missing_stale_and_orphaned_headers(definitions: Path, tmp_path: Path) -> None:
    headers = tmp_path / "node_inputs"
    headers.mkdir()
    assert sorted(node_inputs.stale_headers(definitions, headers)) == [
        "test_no_inputs_inputs.h is missing",
        "test_sockets_inputs.h is missing",
        "test_values_inputs.h is missing",
    ]
    node_inputs.write_headers(definitions, headers)
    assert node_inputs.stale_headers(definitions, headers) == []
    (headers / "test_sockets_inputs.h").write_text("// edited by hand\n")
    (headers / "removed_type_inputs.h").write_text("// its definition is gone\n")
    assert sorted(node_inputs.stale_headers(definitions, headers)) == [
        "removed_type_inputs.h has no definition",
        "test_sockets_inputs.h is out of date",
    ]
    node_inputs.write_headers(definitions, headers)
    assert sorted(p.name for p in headers.iterdir()) == sorted(EXPECTED_FIELDS)


def test_shipped_headers_are_current() -> None:
    assert node_inputs.stale_headers(node_inputs.DEFINITIONS, node_inputs.HEADERS) == []


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
    headers = tmp_path / "node_inputs"
    headers.mkdir()
    node_inputs.write_headers(definitions, headers)
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
