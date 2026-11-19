"""No code that runs inside a zone's SdfChangeBlock calls API downstream of Sdf's notices (docs/plans/cook-module.md).

SdfChangeBlock delays Sdf's notices until it closes, so a UsdStage, Pcp, or Hydra sees stale layers while it's open,
and may hold expired handles: "It is not safe to use Usd or other downstream API while a changeblock is open"
(https://openusd.org/release/api/class_sdf_change_block.html). A zone's task cooks inside one (tree_cook.cpp's
CookZone), and so does every function it reaches: its begin's Template hook, its chain nodes' author functions, its
end's finish, the authoring context, and the layer copy. This reads the cook's C++ sources, follows every call from
those entry points to the functions the sources define, and checks that none of them names a Usd, Pcp, or Hd
identifier, other than UsdUtils' layer-level path pass, which works on Sdf layers only.
"""

from __future__ import annotations

import re
from pathlib import Path

import proscenium_cook

SOURCES = Path(proscenium_cook.__file__).parent / "tree_cook"

# Downstream of Sdf's notices, by the prefixes OpenUSD gives each library's identifiers.
DOWNSTREAM = re.compile(r"\b(?:Usd|Pcp|Hd)\w*")
# UsdUtilsModifyAssetPaths rewrites an Sdf layer's asset paths through the Sdf API, and composes nothing.
ALLOWED = {"UsdUtilsModifyAssetPaths"}

IDENTIFIER_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*(?:<[^<>;{}()]*>)?\s*\(")
# A function's definition: its name, optionally qualified, its parameters, its qualifiers, then its body's brace. A
# constructor's initializer list is allowed between them.
DEFINITION = re.compile(
    r"(?:\b\w+::)?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?(?::[^;{]*?)?\{"
)
KEYWORDS = {"if", "for", "while", "switch", "return", "catch", "sizeof", "static_cast", "decltype", "alignof"}


def _strip(text: str) -> str:
    """The source without comments, string literals, or preprocessor lines, which name things the code doesn't call."""
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r'R"\((?:.|\n)*?\)"', '""', text)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', text)
    return re.sub(r"^\s*#[^\n]*", "", text, flags=re.MULTILINE)


def _body(text: str, brace: int) -> str:
    depth = 0
    for index in range(brace, len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            return text[brace : index + 1]
    return text[brace:]


def _definitions() -> dict[str, list[str]]:
    """Each function the cook's sources define, by unqualified name, with the bodies of its overloads."""
    bodies: dict[str, list[str]] = {}
    for path in sorted([*SOURCES.rglob("*.cpp"), *SOURCES.rglob("*.h")]):
        text = _strip(path.read_text(encoding="utf-8"))
        for match in DEFINITION.finditer(text):
            name = match.group(1)
            if name not in KEYWORDS:
                bodies.setdefault(name, []).append(_body(text, match.end() - 1))
    return bodies


def _registered_hooks() -> set[str]:
    """The functions node_registry.cpp lists that run inside a zone's block.

    Each authoring node's author, and each zone node's startsFrom and finish, the second and third of its ZoneRole's
    four hooks.
    """
    registry = _strip((SOURCES / "nodes" / "node_registry.cpp").read_text(encoding="utf-8"))
    hooks = {match.group(1) for match in re.finditer(r"AuthoringRole\{\s*(\w+)", registry)}
    for match in re.finditer(r"ZoneRole\{\s*\w+\s*,\s*(\w+)\s*,\s*(\w+)", registry):
        hooks |= {name for name in match.groups() if name != "nullptr"}
    return hooks


def _downstream_reached(entry_points: set[str]) -> dict[str, set[str]]:
    """Each function reached from entry_points that names a downstream identifier, with the identifiers it names."""
    definitions = _definitions()
    reached: set[str] = set()
    pending = [name for name in entry_points if name in definitions]
    while pending:
        name = pending.pop()
        if name in reached:
            continue
        reached.add(name)
        for body in definitions[name]:
            pending.extend(
                call for call in IDENTIFIER_CALL.findall(body) if call in definitions and call not in reached
            )
    found: dict[str, set[str]] = {}
    for name in reached:
        named = {identifier for body in definitions[name] for identifier in DOWNSTREAM.findall(body)} - ALLOWED
        if named:
            found[name] = named
    return found


def test_in_block_entry_points_are_found() -> None:
    hooks = _registered_hooks()
    assert {"AuthorCreatePrim", "NewLayerZoneTemplate", "NewLayerZoneFinish"} <= hooks
    definitions = _definitions()
    for name in [*hooks, "CookZone", "CreatePrimSpec", "CopyLayer"]:
        assert name in definitions, name


def test_check_finds_a_stage_call() -> None:
    # A Stage Output composes its stage in its own task, outside any block, so the check, seeded there, finds it.
    assert "ComposedStage" in _downstream_reached({"RunStageOutput"})


def test_nothing_inside_a_zones_change_block_calls_downstream_api() -> None:
    assert _downstream_reached({"CookZone", *_registered_hooks()}) == {}
