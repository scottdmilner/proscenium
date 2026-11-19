"""Write the cook's typed input headers from its node definitions, or check that they're current.

    uv run python tools/node_inputs.py render   # rewrite tree_cook/node_inputs/ from node_definitions.usda
    uv run python tools/node_inputs.py check    # fail if any header there is out of date (a pre-commit hook)

Each node type's header holds a struct of its typed inputs and properties, and the reader that fills it through
tree_cook/node_input_reader.h (docs/plans/cook-module.md "Node types in C++"):
- a value socket or property gets the C++ type of its SdfValueTypeName;
- a Layer input an SdfLayerHandle in a LayerInput, several for a multi-input; a File input a FileInput; a Prim an
  SdfPath; a Prims an SdfPathExpression. An Editable Layer input is its context's, so the struct leaves it out;
- an optional property is an AuthoredField, and a dynamically typed input a VtValue.
Outputs aren't inputs, so no struct holds them. The headers are checked in, formatted with the cook's .clang-format,
so a diff shows what changed in an interface and the build needs no generation step.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pxr import Sdf

import native_build

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "proscenium_cook" / "src" / "proscenium_cook"
DEFINITIONS = PACKAGE / "node_definitions.usda"
HEADERS = PACKAGE / "tree_cook" / "node_inputs"
CLANG_FORMAT_STYLE = PACKAGE / "tree_cook" / ".clang-format"
NAMESPACES = ("inputs:", "props:")
PXR_TYPE = re.compile(r"\b(Gf|Sdf|Tf|Vt)(\w+)")
# The headers outside pxr that a C++ type needs.
STANDARD_HEADERS = {"std::string": "<string>", "std::int64_t": "<cstdint>", "std::uint64_t": "<cstdint>"}
PXR_DIRECTORIES = {"Gf": "base/gf", "Sdf": "usd/sdf", "Tf": "base/tf", "Vt": "base/vt"}


@dataclass(frozen=True)
class InputField:
    """One field of a node type's input struct, and the reader call that fills it."""

    attribute_name: str  # such as inputs:layer
    cpp_type: str
    reader_call: str  # such as Layer("inputs:layer")

    @property
    def member_name(self) -> str:
        """The attribute's name after its namespace, its later namespaces joined in camel case: layer, itemFile."""
        parts = self.attribute_name.split(":")[1:]
        return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def header_name(type_name: str) -> str:
    """A node type's header, in snake case: SetAttribute's is set_attribute_inputs.h."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", type_name).lower() + "_inputs.h"


def value_cpp_type(type_name: Sdf.ValueTypeName) -> str:
    """The C++ type that holds a value of this USD type, qualified as the cook's sources spell it."""
    cpp = re.sub(r"\b(u?int64_t)\b", r"std::\1", type_name.cppTypeName)
    return PXR_TYPE.sub(r"PXR_NS::\1\2", cpp)


def input_field(attribute: Sdf.AttributeSpec) -> InputField | None:
    """The struct field an input or property becomes; None for an Editable Layer input, the context's."""
    name = attribute.name
    custom = dict(attribute.customData)
    socket = custom.get("socket")
    quoted = f'"{name}"'
    if socket == "EditableLayer":
        return None
    if socket == "Layer":
        if custom.get("multiInput"):
            return InputField(name, "std::vector<LayerInput>", f"Layers({quoted})")
        return InputField(name, "LayerInput", f"Layer({quoted})")
    if socket == "File":
        return InputField(name, "FileInput", f"File({quoted})")
    if socket == "Prim":
        return InputField(name, "PXR_NS::SdfPath", f"Prim({quoted})")
    if socket == "Prims":
        return InputField(name, "PXR_NS::SdfPathExpression", f"Prims({quoted})")
    if custom.get("dynamicType"):
        return InputField(name, "PXR_NS::VtValue", f"Dynamic({quoted})")
    cpp = value_cpp_type(attribute.typeName)
    if custom.get("optional"):
        return InputField(name, f"AuthoredField<{cpp}>", f"Optional<{cpp}>({quoted})")
    return InputField(name, cpp, f"Value<{cpp}>({quoted})")


def _includes(fields: list[InputField]) -> list[str]:
    """The headers the fields' types need beyond node_input_reader.h, which declares the reader's own types."""
    pxr = {"pxr/pxr.h"}
    standard: set[str] = set()
    for field in fields:
        pxr |= {
            f"pxr/{PXR_DIRECTORIES[p]}/{rest[:1].lower() + rest[1:]}.h" for p, rest in PXR_TYPE.findall(field.cpp_type)
        }
        standard |= {header for cpp, header in STANDARD_HEADERS.items() if cpp in field.cpp_type}
        if field.cpp_type.startswith("std::vector"):
            standard.add("<vector>")
    lines = [f"#include <{header}>" for header in sorted(pxr)]
    return [*lines, "", *(f"#include {header}" for header in sorted(standard))] if standard else lines


def render_header(prim: Sdf.PrimSpec, definitions_name: str) -> str:
    """A node type's header, before clang-format."""
    type_name = prim.name
    fields = [
        field
        for attribute in prim.attributes
        if attribute.name.startswith(NAMESPACES) and (field := input_field(attribute)) is not None
    ]
    names = [field.member_name for field in fields]
    if len(set(names)) != len(names):
        raise SystemExit(f"{type_name}: two inputs or properties share a member name: {names}")
    members = "\n".join(f"  {field.cpp_type} {field.member_name}{{}};  // {field.attribute_name}" for field in fields)
    reads = "\n".join(f"  inputs.{field.member_name} = reader.{field.reader_call};" for field in fields)
    unused = "" if fields else "  static_cast<void>(reader);\n"
    return "\n".join(
        [
            f"// {type_name}'s inputs and properties, generated by tools/node_inputs.py from {definitions_name}. Don't",
            "// edit it: change the definition and run `uv run python tools/node_inputs.py render`.",
            "#pragma once",
            "",
            *_includes(fields),
            "",
            '#include "node_input_reader.h"',
            "",
            "namespace proscenium {",
            "",
            f"struct {type_name}Inputs {{",
            members,
            "};",
            "",
            f"inline {type_name}Inputs Read{type_name}Inputs(const NodeInputReader& reader) {{",
            f"  {type_name}Inputs inputs;",
            reads + unused.rstrip("\n"),
            "  return inputs;",
            "}",
            "",
            "}  // namespace proscenium",
            "",
        ]
    )


def _clang_format(text: str, assume_path: Path) -> str:
    """The header as the cook's clang-format style lays it out, as the pre-commit hook would."""
    command = [
        native_build.tool("clang-format"),
        f"--style=file:{CLANG_FORMAT_STYLE}",
        f"--assume-filename={assume_path}",
    ]
    return subprocess.run(command, input=text, capture_output=True, text=True, check=True).stdout


def render(definitions: Path, headers: Path) -> dict[Path, str]:
    """Each node type's header, formatted, by its path in headers."""
    layer = Sdf.Layer.OpenAsAnonymous(str(definitions))
    if layer is None:
        raise SystemExit(f"Can't read the node definitions file {definitions}")
    rendered: dict[Path, str] = {}
    for prim in layer.rootPrims:
        path = headers / header_name(prim.name)
        rendered[path] = _clang_format(render_header(prim, definitions.name), path)
    return rendered


def stale_headers(definitions: Path, headers: Path) -> list[str]:
    """What differs between the headers in headers and those the definitions give: one line each."""
    rendered = render(definitions, headers)
    existing = set(headers.glob("*_inputs.h"))
    problems = [f"{p.name} is missing" for p in rendered if p not in existing]
    problems += [f"{p.name} is out of date" for p, text in rendered.items() if p in existing and p.read_text() != text]
    problems += [f"{p.name} has no definition" for p in sorted(existing - set(rendered))]
    return problems


def write_headers(definitions: Path, headers: Path) -> None:
    """Rewrite headers' generated files from the definitions, removing any whose definition is gone."""
    rendered = render(definitions, headers)
    for stale in set(headers.glob("*_inputs.h")) - set(rendered):
        stale.unlink()
    for path, text in rendered.items():
        if not path.is_file() or path.read_text() != text:
            path.write_text(text)
            print(f"wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")


def main() -> int:
    """Run render or check; exit 1 when check finds a stale header."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["check", "render"])
    args = parser.parse_args()
    if args.command == "render":
        write_headers(DEFINITIONS, HEADERS)
        return 0
    problems = stale_headers(DEFINITIONS, HEADERS)
    if problems:
        print("\n".join([*problems, "run `uv run python tools/node_inputs.py render`"]))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
