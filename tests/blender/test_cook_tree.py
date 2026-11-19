"""The temporary UI's cook tree: node types from the definitions, the tree's layer, and its cook (cook-module plan).

Each test builds a tree through bpy as a user would, then reads the layer it writes or the stages its cook returns.
Expected values come from how the test built its tree and from the note's tree format (docs/phase3/node-tree.md "The
tree as plain data").
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import bpy
from pxr import Sdf, Usd

import proscenium_cook
from fixtures.scenes import Scene, copy_scene
from proscenium.interface import cook_node_types, cook_panel, cook_tree_layer
from support.recording_layout import RecordingLayout

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


def _tree() -> Any:
    node_groups: Any = bpy.data.node_groups  # the stubs list only Blender's own tree types
    return node_groups.new("Tree", cook_node_types.TREE_IDNAME)


def _node(tree: Any, type_name: str, name: str) -> Any:
    node = tree.nodes.new(f"ProsceniumCook{type_name}")
    node.name = name
    return node


def _link(tree: Any, from_node: Any, output: str, to_node: Any, input_identifier: str) -> Any:
    from_socket = next(socket for socket in from_node.outputs if socket.identifier == output)
    to_socket = next(socket for socket in to_node.inputs if socket.identifier == input_identifier)
    return tree.links.new(from_socket, to_socket)


def _zone_tree() -> tuple[Any, dict[str, Any]]:
    """Begin -> Create Prim.001 (/Chair, an Xform) -> a reroute -> End -> a Stage Output and the chosen Viewer."""
    tree = _tree()
    nodes = {
        "begin": _node(tree, "NewLayerZoneBegin", "Begin"),
        "create": _node(tree, "CreatePrim", "Create Prim.001"),
        "end": _node(tree, "NewLayerZoneEnd", "End"),
        "output": _node(tree, "StageOutput", "Stage Output"),
        "viewer": _node(tree, "Viewer", "Viewer"),
    }
    nodes["begin"].zone_end = "End"
    nodes["create"].inputs["Name"].default_value = "Chair"
    nodes["create"].prop_type = "Xform"
    reroute = tree.nodes.new("NodeReroute")
    _link(tree, nodes["begin"], "layer", nodes["create"], "editableLayer")
    tree.links.new(nodes["create"].outputs["Editable Layer"], reroute.inputs[0])
    tree.links.new(reroute.outputs[0], nodes["end"].inputs["Layer"])
    _link(tree, nodes["end"], "layer", nodes["output"], "layer")
    _link(tree, nodes["end"], "layer", nodes["viewer"], "layer")
    tree.viewer = "Viewer"
    return tree, nodes


def _tree_layer(tree: Any) -> Sdf.Layer:
    layer = Sdf.Layer.CreateAnonymous()
    cook_tree_layer.write_tree_layer(tree, layer)
    return layer


def test_each_definition_is_a_node_type_with_its_sockets(extension: ModuleType) -> None:
    del extension
    definitions = Sdf.Layer.FindOrOpen(str(proscenium_cook.NODE_DEFINITIONS_PATH))
    by_type = {node_type.cook_definition.type_name: node_type for node_type in cook_node_types.node_types()}
    assert sorted(by_type) == sorted(prim.name for prim in definitions.rootPrims)
    tree = _tree()
    for prim in definitions.rootPrims:
        node = tree.nodes.new(by_type[prim.name].bl_idname)
        names = [attribute.name for attribute in prim.attributes]
        assert [f"inputs:{socket.identifier}" for socket in node.inputs] == [
            n for n in names if n.startswith("inputs:")
        ]
        assert [f"outputs:{socket.identifier}" for socket in node.outputs] == [
            n for n in names if n.startswith("outputs:")
        ]
        for name in names:
            if name.startswith("props:"):
                assert hasattr(node, f"prop_{name.removeprefix('props:')}"), (prim.name, name)


def test_tree_layer_follows_the_tree_format(extension: ModuleType) -> None:
    del extension
    tree, nodes = _zone_tree()
    nodes["output"].mute = True
    layer = _tree_layer(tree)
    root = layer.GetPrimAtPath("/Tree")
    assert root.typeName == "NodeTree"
    assert root.attributes["tree:format"].default == 1
    create = layer.GetPrimAtPath("/Tree/Create_20_Prim_2e_001")  # the note's encoding of "Create Prim.001"
    assert create.typeName == "CreatePrim"
    assert create.attributes["node:version"].default == 1
    assert create.attributes["inputs:name"].default == "Chair"
    assert create.attributes["props:type"].default == "Xform"
    assert "inputs:parent" not in create.attributes  # left at its definition's default, so unauthored
    assert "props:specifier" not in create.attributes
    assert "node:mute" not in create.attributes  # authored only when true
    end_input = layer.GetPrimAtPath("/Tree/End").attributes["inputs:layer"]
    # The reroute is stripped: End's link names the Create Prim it starts from.
    assert list(end_input.connectionPathList.explicitItems) == [
        Sdf.Path("/Tree/Create_20_Prim_2e_001.outputs:editableLayer")
    ]
    assert list(layer.GetPrimAtPath("/Tree/Begin").relationships["zone:end"].targetPathList.explicitItems) == [
        Sdf.Path("/Tree/End")
    ]
    assert layer.GetPrimAtPath("/Tree/Stage_20_Output").attributes["node:mute"].default is True


def test_muted_link_is_left_out(extension: ModuleType) -> None:
    del extension
    tree, nodes = _zone_tree()
    next(link for link in tree.links if link.to_node == nodes["output"]).is_muted = True
    layer = _tree_layer(tree)
    assert "inputs:layer" not in layer.GetPrimAtPath("/Tree/Stage_20_Output").attributes


def test_zone_tree_cooks_to_its_stages(extension: ModuleType) -> None:
    del extension
    tree, _nodes = _zone_tree()
    result = cook_panel.cook_tree(tree)
    assert result.tree_diagnostics == ()
    for stage in (result.stage_outputs["Stage Output"], result.viewer_stage):
        assert stage is not None
        chair = stage.GetPrimAtPath("/Chair")
        assert chair.IsDefined()
        assert chair.GetTypeName() == "Xform"
    # The zone's report names the node that wrote the prim spec by its Blender name.
    assert result.node_reports["Begin"].report_data["primSpecs"] == {"/Chair": "Create Prim.001"}


def test_a_kept_cook_returns_the_same_stage(extension: ModuleType) -> None:
    del extension
    tree, nodes = _zone_tree()
    first = cook_panel.cook_tree(tree).stage_outputs["Stage Output"]
    nodes["create"].inputs["Name"].default_value = "Table"
    second = cook_panel.cook_tree(tree).stage_outputs["Stage Output"]
    assert first == second  # the zone's layer is kept, so the Stage Output's stage is
    assert second.GetPrimAtPath("/Table").IsDefined()
    assert not second.GetPrimAtPath("/Chair")


def test_no_chosen_viewer_cooks_none(extension: ModuleType) -> None:
    del extension
    tree, nodes = _zone_tree()
    tree.viewer = ""
    tree.nodes.active = nodes["viewer"]  # the active node doesn't choose the Viewer
    result = cook_panel.cook_tree(tree)
    assert cook_panel.active_viewer(tree) is None
    assert result.viewer_stage is None
    assert "Stage Output" in result.stage_outputs


def test_viewer_dropdown_offers_only_viewers(extension: ModuleType) -> None:
    del extension
    tree, _nodes = _zone_tree()
    _node(tree, "Viewer", "Another Viewer")
    assert sorted(cook_node_types.viewer_names(tree)) == ["Another Viewer", "Viewer"]
    tree.viewer = "Another Viewer"
    assert cook_panel.active_viewer(tree) == "Another Viewer"


def test_viewer_name_of_a_deleted_viewer_is_the_cooks_warning(extension: ModuleType) -> None:
    del extension
    tree, nodes = _zone_tree()
    tree.nodes.remove(nodes["viewer"])
    result = cook_panel.cook_tree(tree)
    assert [d.code for d in result.tree_diagnostics] == [proscenium_cook.DiagnosticCode.UNKNOWN_VIEWER]
    assert result.viewer_stage is None
    layout = RecordingLayout()
    panel: Any = SimpleNamespace(layout=layout)
    cook_panel.PROSCENIUM_PT_cook_tree.draw(panel, SimpleNamespace(space_data=SimpleNamespace(edit_tree=tree)))
    assert layout.labels == [("No Viewer is named 'Viewer'", "ERROR", True)]


def test_layer_from_file_reads_its_path(extension: ModuleType, tmp_path: Path) -> None:
    del extension
    chair = copy_scene(Scene.COOK_TREES, tmp_path) / "chair.usda"
    tree = _tree()
    reader = _node(tree, "LayerFromFile", "Chair File")
    reader.prop_path = str(chair)
    output = _node(tree, "StageOutput", "Stage Output")
    _link(tree, reader, "layer", output, "layer")
    stage = cook_panel.cook_tree(tree).stage_outputs["Stage Output"]
    assert isinstance(stage, Usd.Stage)
    assert stage.GetPrimAtPath("/Chair/Seat").GetTypeName() == "Cube"  # chair.usda's own prims


def test_relative_path_in_an_unsaved_file_is_reported(extension: ModuleType) -> None:
    del extension
    tree = _tree()
    _node(tree, "LayerFromFile", "Chair File").prop_path = "//chair.usda"
    result = cook_panel.cook_tree(tree)
    codes = [diagnostic.code for diagnostic in result.node_reports["Chair File"].diagnostics]
    assert codes == [proscenium_cook.DiagnosticCode.MISSING_BASE_DIRECTORY]
    report = cook_panel.cook_report(tree, result, with_tree_layer=True)
    assert "missing-base-directory" in report
    assert 'def LayerFromFile "Chair_20_File"' in report


def test_zone_tree_has_no_incompatible_links(extension: ModuleType) -> None:
    # Every link _zone_tree makes is one the cook takes, the Editable Layer into the Viewer among them.
    del extension
    tree, _nodes = _zone_tree()
    assert cook_node_types.mark_incompatible_links(tree) == 0
    assert all(link.is_valid for link in tree.links)


def test_link_the_cook_rejects_is_red_and_reported(extension: ModuleType) -> None:
    del extension
    tree = _tree()
    reader = _node(tree, "LayerFromFile", "Reader")
    create = _node(tree, "CreatePrim", "Create Prim")
    begin = _node(tree, "NewLayerZoneBegin", "Begin")
    output = _node(tree, "StageOutput", "Stage Output")
    _link(tree, reader, "layer", create, "parent")  # a Layer into a Prim input
    _link(tree, begin, "layer", output, "layer")  # an Editable Layer into a Layer input that takes none
    # Background Blender runs no timers, so the test marks the links the tree's update would.
    assert cook_node_types.mark_incompatible_links(tree) == 2
    assert [link.is_valid for link in tree.links] == [False, False]
    # The links stay in the tree's layer, and the cook reports each on the node it enters.
    result = cook_panel.cook_tree(tree)
    for node_id in ("Create Prim", "Stage Output"):
        codes = [diagnostic.code for diagnostic in result.node_reports[node_id].diagnostics]
        assert proscenium_cook.DiagnosticCode.INCOMPATIBLE_LINK in codes, node_id


def test_link_through_a_reroute_is_checked_from_its_start(extension: ModuleType) -> None:
    del extension
    tree = _tree()
    reader = _node(tree, "LayerFromFile", "Reader")
    create = _node(tree, "CreatePrim", "Create Prim")
    reroute = tree.nodes.new("NodeReroute")
    into_reroute = tree.links.new(reader.outputs["Layer"], reroute.inputs[0])
    into_create = tree.links.new(reroute.outputs[0], create.inputs["Parent"])
    cook_node_types.mark_incompatible_links(tree)
    # The reroute's own link is valid; the one into the Prim input, which would bring a Layer, is red.
    assert into_reroute.is_valid
    assert not into_create.is_valid


def test_panel_draws_the_cook_button_and_the_trees_properties(extension: ModuleType) -> None:
    del extension
    tree, _nodes = _zone_tree()
    layout = RecordingLayout()
    panel: Any = SimpleNamespace(layout=layout)
    context = SimpleNamespace(space_data=SimpleNamespace(edit_tree=tree))
    cook_panel.PROSCENIUM_PT_cook_tree.draw(panel, context)
    assert [drawn.idname for drawn in layout.operators] == ["proscenium.cook_tree"]  # one button
    # Both on the tree, kept per tree.
    assert layout.props == [cook_node_types.PRINT_TREE_LAYER_PROPERTY, cook_node_types.VIEWER_PROPERTY]
    assert layout.labels == []  # the chosen Viewer is one
