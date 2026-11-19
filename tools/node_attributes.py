"""Write the cook's typed attribute headers from its node definitions, or check that they're current.

    uv run python tools/node_attributes.py render   # rewrite tree_cook/nodes/*_attributes.h from node_definitions.usda
    uv run python tools/node_attributes.py check    # fail if any of them is out of date (a pre-commit hook)

Each node type's header sits beside its .cpp in tree_cook/nodes/ and holds two structs (docs/plans/cook-module.md
"Node types in C++"): its typed inputs and properties, with the reader that fills them through
tree_cook/node_input_reader.h, and its typed outputs, with the writer that commits them by name.
- A value socket or property gets the C++ type of its SdfValueTypeName.
- A Layer input is an SdfLayerHandle in a LayerInput, several for a multi-input; a File input a FileInput; a Prim an
  SdfPath; a Prims an SdfPathExpression. An output of each kind has the same type, with a Layer's handle and a File's
  identifier held bare.
- An Editable Layer input or output is its context's, so neither struct holds it.
- An optional property is an AuthoredField, and a dynamically typed input or output a VtValue.
- A member is named for its attribute, in camel case, with a trailing underscore for a C++ keyword: inputs:template's
  is template_, named by the constant kTemplate.
The headers are checked in, formatted with the cook's .clang-format, so a diff shows what changed in an interface and
the build needs no generation step.
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
HEADERS = PACKAGE / "tree_cook" / "nodes"
HEADER_SUFFIX = "_attributes.h"
CLANG_FORMAT_STYLE = PACKAGE / "tree_cook" / ".clang-format"
INPUT_NAMESPACES = ("inputs:", "props:")
OUTPUT_NAMESPACE = "outputs:"
PXR_TYPE = re.compile(r"\b(Gf|Sdf|Tf|Vt)(\w+)")
# The headers outside pxr that a C++ type needs.
STANDARD_HEADERS = {"std::string": "<string>", "std::int64_t": "<cstdint>", "std::uint64_t": "<cstdint>"}
PXR_DIRECTORIES = {"Gf": "base/gf", "Sdf": "usd/sdf", "Tf": "base/tf", "Vt": "base/vt"}
# Types declared in a header of another name.
PXR_HEADERS = {"SdfLayerHandle": "pxr/usd/sdf/layer.h"}
# C++20's keywords and alternative tokens, which a member name can't be.
CPP_KEYWORDS = frozenset(
    """alignas alignof and and_eq asm auto bitand bitor bool break case catch char char16_t char32_t char8_t class
    co_await co_return co_yield compl concept const const_cast consteval constexpr constinit continue decltype
    default delete do double dynamic_cast else enum explicit export extern false float for friend goto if inline
    int long mutable namespace new noexcept not not_eq nullptr operator or or_eq private protected public
    register reinterpret_cast requires return short signed sizeof static static_assert static_cast struct switch
    template this thread_local throw true try typedef typeid typename union unsigned using virtual void volatile
    wchar_t while xor xor_eq""".split()
)


@dataclass(frozen=True)
class InputField:
    """One field of a node type's input struct, and the reader call that fills it."""

    attribute_name: str  # such as inputs:layer
    cpp_type: str
    reader_call: str  # such as Layer("inputs:layer")

    @property
    def member_name(self) -> str:
        """The attribute's name after its namespace, later namespaces joined in camel case: layer, itemFile, template_.

        A C++ keyword takes a trailing underscore.
        """
        return _member_name(self.attribute_name)

    @property
    def constant_name(self) -> str:
        """The struct's constant naming the field's attribute: kPath for props:path, kTemplate for inputs:template."""
        return _constant_name(self.attribute_name)


@dataclass(frozen=True)
class OutputField:
    """One field of a node type's output struct, and how the writer commits it."""

    attribute_name: str  # such as outputs:layer
    cpp_type: str
    # The value the writer commits, given the member's expression; the type a linked input reads
    # (node_input_reader.h): the value's own, a Layer's SdfLayerHandle, or a File's, Prim's, or Prims' string.
    committed: str  # such as "{member}.GetAsString()"
    # Whether the member holds something to commit, given its expression; "" when it always does, as a value does.
    present: str  # such as "!{member}.IsEmpty()"

    @property
    def member_name(self) -> str:
        """The attribute's name after its namespace, later namespaces joined in camel case: layer, itemFile, template_.

        A C++ keyword takes a trailing underscore.
        """
        return _member_name(self.attribute_name)

    @property
    def constant_name(self) -> str:
        """The struct's constant naming the field's attribute: kPath for props:path, kTemplate for inputs:template."""
        return _constant_name(self.attribute_name)


def _camel_name(attribute_name: str) -> str:
    parts = attribute_name.split(":")[1:]
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _member_name(attribute_name: str) -> str:
    # A C++ keyword, such as inputs:template's, takes a trailing underscore.
    name = _camel_name(attribute_name)
    return name + "_" if name in CPP_KEYWORDS else name


def _constant_name(attribute_name: str) -> str:
    name = _camel_name(attribute_name)
    return "k" + name[:1].upper() + name[1:]


def header_name(type_name: str) -> str:
    """A node type's header, in snake case beside its .cpp: SetAttribute's is set_attribute_attributes.h."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", type_name).lower() + HEADER_SUFFIX


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


def output_field(attribute: Sdf.AttributeSpec) -> OutputField | None:
    """The struct field an output becomes; None for an Editable Layer output, the context's."""
    name = attribute.name
    custom = dict(attribute.customData)
    socket = custom.get("socket")
    if socket == "EditableLayer":
        return None
    if socket == "Layer":
        return OutputField(name, "PXR_NS::SdfLayerHandle", "{member}", "{member}")
    if socket == "File":
        return OutputField(name, "std::string", "{member}", "!{member}.empty()")
    if socket == "Prim":
        return OutputField(name, "PXR_NS::SdfPath", "{member}.GetAsString()", "!{member}.IsEmpty()")
    if socket == "Prims":
        return OutputField(name, "PXR_NS::SdfPathExpression", "{member}.GetText()", "!{member}.IsEmpty()")
    if custom.get("dynamicType"):
        return OutputField(name, "PXR_NS::VtValue", "{member}", "!{member}.IsEmpty()")
    return OutputField(name, value_cpp_type(attribute.typeName), "{member}", "")


def _includes(fields: list[InputField | OutputField]) -> list[str]:
    """The headers the fields' types need beyond node_input_reader.h, which declares the reader's own types."""
    pxr = {"pxr/pxr.h"}
    standard: set[str] = set()
    for field in fields:
        pxr |= {
            PXR_HEADERS.get(p + rest, f"pxr/{PXR_DIRECTORIES[p]}/{rest[:1].lower() + rest[1:]}.h")
            for p, rest in PXR_TYPE.findall(field.cpp_type)
        }
        standard |= {header for cpp, header in STANDARD_HEADERS.items() if cpp in field.cpp_type}
        if field.cpp_type.startswith("std::vector"):
            standard.add("<vector>")
    lines = [f"#include <{header}>" for header in sorted(pxr)]
    return [*lines, "", *(f"#include {header}" for header in sorted(standard))] if standard else lines


def _check_member_names(type_name: str, fields: list[InputField] | list[OutputField]) -> None:
    names = [field.member_name for field in fields]
    if len(set(names)) != len(names):
        raise SystemExit(f"{type_name}: two attributes of one struct share a member name: {names}")


def _commit(field: OutputField) -> str:
    """The writer's lines for one output: commit its value, unless it holds nothing."""
    member = f"outputs.{field.member_name}"
    commit = (
        f'values[PXR_NS::TfToken("{field.attribute_name}")] = PXR_NS::VtValue({field.committed.format(member=member)});'
    )
    if not field.present:
        return f"  {commit}"
    return f"  if ({field.present.format(member=member)}) {{\n    {commit}\n  }}"


def render_header(prim: Sdf.PrimSpec, definitions_name: str) -> str:
    """A node type's header, before clang-format."""
    type_name = prim.name
    inputs = [
        field
        for attribute in prim.attributes
        if attribute.name.startswith(INPUT_NAMESPACES) and (field := input_field(attribute)) is not None
    ]
    outputs = [
        field
        for attribute in prim.attributes
        if attribute.name.startswith(OUTPUT_NAMESPACE) and (field := output_field(attribute)) is not None
    ]
    _check_member_names(type_name, inputs)
    _check_member_names(type_name, outputs)

    def members(fields: list[InputField] | list[OutputField]) -> str:
        # Each attribute's name, such as kPath for props:path, for the node's diagnostics and links; then its field.
        names = [
            f'  static constexpr const char* {field.constant_name} = "{field.attribute_name}";' for field in fields
        ]
        values = [f"  {field.cpp_type} {field.member_name}{{}};" for field in fields]
        return "\n".join([*names, *([""] if names else []), *values])

    reads = "\n".join(f"  inputs.{field.member_name} = reader.{field.reader_call};" for field in inputs)
    reads_unused = "" if inputs else "  static_cast<void>(reader);"
    commits = "\n".join(_commit(field) for field in outputs)
    commits_unused = "" if outputs else "  static_cast<void>(outputs);"
    return "\n".join(
        [
            f"// {type_name}'s typed attributes, generated by tools/node_attributes.py from {definitions_name}: its",
            "// inputs and properties, read by name, and its outputs, committed by name. Don't edit it: change the",
            "// definition and run `uv run python tools/node_attributes.py render`.",
            "#pragma once",
            "",
            *_includes([*inputs, *outputs]),
            "",
            '#include "node_input_reader.h"',
            '#include "node_roles.h"',
            "",
            "namespace proscenium {",
            "",
            f"struct {type_name}Inputs {{",
            members(inputs),
            "};",
            "",
            f"inline {type_name}Inputs Read{type_name}Inputs(const NodeInputReader& reader) {{",
            f"  {type_name}Inputs inputs;",
            reads or reads_unused,
            "  return inputs;",
            "}",
            "",
            "// What the node outputs; an output left empty, such as a null layer, commits nothing.",
            f"struct {type_name}Outputs {{",
            members(outputs),
            "};",
            "",
            f"inline ValueOutputs Write{type_name}Outputs(const {type_name}Outputs& outputs) {{",
            "  ValueOutputs values;",
            commits or commits_unused,
            "  return values;",
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
    existing = set(headers.glob(f"*{HEADER_SUFFIX}"))
    problems = [f"{p.name} is missing" for p in rendered if p not in existing]
    problems += [f"{p.name} is out of date" for p, text in rendered.items() if p in existing and p.read_text() != text]
    problems += [f"{p.name} has no definition" for p in sorted(existing - set(rendered))]
    return problems


def write_headers(definitions: Path, headers: Path) -> None:
    """Rewrite headers' generated files from the definitions, removing any whose definition is gone."""
    rendered = render(definitions, headers)
    for stale in set(headers.glob(f"*{HEADER_SUFFIX}")) - set(rendered):
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
        print("\n".join([*problems, "run `uv run python tools/node_attributes.py render`"]))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
