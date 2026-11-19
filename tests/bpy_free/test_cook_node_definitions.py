"""The cook's node definitions loader (docs/phase3/node-tree.md "Node definitions").

The shipped definitions and the node registry name the same node types, and a malformed definition is refused, naming
its problem.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import proscenium_cook
from fixtures.scenes import Scene, copy_scene
from proscenium_cook.tree_cook import NodeDefinitions

SHIPPED_DEFINITIONS = Path(proscenium_cook.__file__).parent / "node_definitions.usda"


def test_shipped_definitions_match_the_registry() -> None:
    # Loading checks each definition against the registry and the reverse; neither has a node type before step 4.
    assert NodeDefinitions(str(SHIPPED_DEFINITIONS)).type_names() == []


def test_definitions_without_implementations_are_refused(tmp_path: Path) -> None:
    definitions = copy_scene(Scene.COOK_DEFINITIONS, tmp_path) / "test_node_definitions.usda"
    with pytest.raises(ValueError, match="malformed") as raised:
        NodeDefinitions(str(definitions))
    for type_name in ("TestSockets", "TestValues", "TestNoInputs"):
        assert f"{type_name}: no implementation" in str(raised.value)


@pytest.mark.parametrize(
    ("type_name", "problem"),
    [
        ("NotAClass", "a definition must be a class prim"),
        ("NoVersion", "node:version must be an int of at least 1"),
        ("UnknownSocketKind", 'unknown socket kind "Mesh"'),
        ("LayerNotOpaque", "a Layer socket must be opaque"),
        ("OpaqueWithoutSocket", "an opaque attribute must name its socket kind"),
        ("AttributeOutsideNamespaces", "not an inputs:, outputs:, or props: attribute"),
        ("MultiInputOutput", "only a Layer input takes several links"),
        ("MultiInputPrim", "only a Layer input takes several links"),
        ("OptionalInput", "only a property is optional"),
        ("PassThroughToNothing", "mutePassThrough names no input"),
        ("PassThroughOtherKind", "mutePassThrough names an input of another kind or type"),
    ],
)
def test_malformed_definition_names_its_problem(tmp_path: Path, type_name: str, problem: str) -> None:
    definitions = copy_scene(Scene.COOK_DEFINITIONS, tmp_path) / "malformed_node_definitions.usda"
    with pytest.raises(ValueError, match="malformed") as raised:
        NodeDefinitions(str(definitions))
    assert [line for line in str(raised.value).splitlines() if line.startswith(type_name) and problem in line]
