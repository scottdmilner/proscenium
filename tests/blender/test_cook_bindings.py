"""The temporary UI's cook into bindings: each Stage Output's stage handed to a binding of its own and synchronized.

Each test builds a tree through bpy as a user would, cooks it as the Cook operator does (cook_panel.cook_tree, then
cook_bindings.synchronize_stage_outputs), and reads the scene's bindings and their displays. Expected values come from
how the test built its tree and from the stage-output-bindings plan.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import bpy

from proscenium.interface import cook_bindings, cook_node_types, cook_panel
from proscenium_sync.results import ResultState
from support.blend import prim_name, save_and_reopen
from support.destinations import destination
from support.recording_layout import RecordingLayout

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium_sync.bindings import BindingHandle, Bindings


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _node(tree: Any, type_name: str, name: str) -> Any:
    node = tree.nodes.new(f"ProsceniumCook{type_name}")
    node.name = name
    return node


def _cube_tree(*outputs: str) -> tuple[Any, dict[str, Any]]:
    """Begin -> Create Prim (/Chair, a Cube) -> End -> a Stage Output for each of outputs."""
    node_groups: Any = bpy.data.node_groups  # the stubs list only Blender's own tree types
    tree = node_groups.new("Tree", cook_node_types.TREE_IDNAME)
    nodes = {
        "begin": _node(tree, "NewLayerZoneBegin", "Begin"),
        "create": _node(tree, "CreatePrim", "Create Prim"),
        "end": _node(tree, "NewLayerZoneEnd", "End"),
    }
    nodes["begin"].zone_end = "End"
    nodes["create"].inputs["Name"].default_value = "Chair"
    nodes["create"].prop_type = "Cube"
    tree.links.new(nodes["begin"].outputs["Layer"], nodes["create"].inputs["Editable Layer"])
    tree.links.new(nodes["create"].outputs["Editable Layer"], nodes["end"].inputs["Layer"])
    for name in outputs:
        nodes[name] = _node(tree, "StageOutput", name)
        tree.links.new(nodes["end"].outputs["Layer"], nodes[name].inputs["Layer"])
    return tree, nodes


def _cook(tree: Any) -> dict[str, cook_bindings.StageOutputSync]:
    """Cook tree and synchronize its Stage Outputs, as the Cook operator does; what each did, by node name."""
    result = cook_panel.cook_tree(tree)
    return {sync.node_id: sync for sync in cook_bindings.synchronize_stage_outputs(tree, result)}


def _handle(bindings: Bindings, node: Any) -> BindingHandle:
    """The scene's binding the node names."""
    return next(h for h in bindings.in_scene(_scene()) if h.binding_id == node.binding_id)


def _applied_conversion(handle: BindingHandle) -> bool:
    """The coordinate conversion of the binding's published display."""
    applied = handle.applied_settings()
    assert applied is not None  # it's published
    return applied.coordinate_conversion


def _displayed(handle: BindingHandle) -> list[str]:
    """The prims the binding's display shows, by name."""
    return sorted(prim_name(obj) for obj in destination(handle).all_objects)


def test_a_cook_makes_a_binding_for_each_stage_output_and_displays_its_stage(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output", "Stage Output.001")
    synchronized = _cook(tree)
    assert {sync.result.state for sync in synchronized.values() if sync.result} == {ResultState.SUCCESS}
    named = sorted(nodes[name].binding_id for name in ("Stage Output", "Stage Output.001"))
    assert sorted(h.binding_id for h in bindings.in_scene(_scene())) == named
    assert "" not in named
    for name in ("Stage Output", "Stage Output.001"):
        handle = _handle(bindings, nodes[name])
        assert synchronized[name].binding_id == handle.binding_id
        assert destination(handle).name == f"Tree {name}"
        assert handle.live_stage() == cook_panel.cook_tree(tree).stage_outputs[name]
        assert _displayed(handle) == ["Chair"]


def test_a_second_cook_reuses_the_binding_and_shows_the_change(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output")
    _cook(tree)
    handle = _handle(bindings, nodes["Stage Output"])
    stage = handle.live_stage()
    nodes["create"].inputs["Name"].default_value = "Table"
    synchronized = _cook(tree)["Stage Output"]
    assert synchronized.binding_id == handle.binding_id
    assert synchronized.result is not None and synchronized.result.state is ResultState.SUCCESS
    assert bindings.in_scene(_scene()) == [handle]
    assert handle.live_stage() == stage  # the kept cook's stage, so it wasn't attached again
    assert _displayed(handle) == ["Table"]


def test_the_coordinate_conversion_property_is_the_bindings_setting(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output")
    nodes["Stage Output"].prop_coordinateConversion = True
    _cook(tree)
    handle = _handle(bindings, nodes["Stage Output"])
    assert _applied_conversion(handle) is True
    nodes["Stage Output"].prop_coordinateConversion = False
    _cook(tree)
    assert _applied_conversion(handle) is False


def test_a_copied_trees_stage_output_gets_its_own_binding(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output")
    _cook(tree)
    original = _handle(bindings, nodes["Stage Output"])
    copy = tree.copy()
    _cook(copy)
    copied = _handle(bindings, copy.nodes["Stage Output"])
    assert copied != original
    assert nodes["Stage Output"].binding_id == original.binding_id
    assert sorted(bindings.in_scene(_scene()), key=str) == sorted([original, copied], key=str)
    assert _displayed(original) == _displayed(copied) == ["Chair"]


def test_a_reopened_file_reattaches_the_same_binding(bindings: Bindings, tmp_path: Path) -> None:
    tree, nodes = _cube_tree("Stage Output")
    tree.use_fake_user = True  # a tree nothing uses isn't saved
    _cook(tree)
    binding_id = nodes["Stage Output"].binding_id
    save_and_reopen(tmp_path / "cooked.blend")
    tree = bpy.data.node_groups["Tree"]
    handle = _handle(bindings, tree.nodes["Stage Output"])
    assert handle.binding_id == binding_id
    assert handle.live_stage() is None  # the load dropped the kept cooks and the bindings' stages
    synchronized = _cook(tree)["Stage Output"]
    assert synchronized.result is not None and synchronized.result.state is ResultState.SUCCESS
    assert bindings.in_scene(_scene()) == [handle]
    assert handle.live_stage() == cook_panel.cook_tree(tree).stage_outputs["Stage Output"]
    assert _displayed(handle) == ["Chair"]


def test_a_stage_output_with_no_scene_makes_no_binding_and_says_why(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output")
    nodes["Stage Output"].scene = None
    synchronized = _cook(tree)["Stage Output"]
    assert synchronized == cook_bindings.StageOutputSync("Stage Output", None, None, cook_bindings.NO_SCENE)
    assert bindings.in_scene(_scene()) == []
    assert cook_bindings.sync_report_lines([synchronized]) == [
        "  Stage Output 'Stage Output', no binding: No scene, so no binding"
    ]
    layout = RecordingLayout()
    panel: Any = SimpleNamespace(layout=layout)
    cook_panel.PROSCENIUM_PT_cook_tree.draw(panel, SimpleNamespace(space_data=SimpleNamespace(edit_tree=tree)))
    assert layout.labels == [("Stage Output: No scene, so no binding", "ERROR", True)]


def test_an_unlinked_stage_output_makes_no_binding_and_the_cook_says_why(bindings: Bindings) -> None:
    tree, nodes = _cube_tree()
    nodes["output"] = _node(tree, "StageOutput", "Stage Output")
    result = cook_panel.cook_tree(tree)
    synchronized = cook_bindings.synchronize_stage_outputs(tree, result)
    assert synchronized == [cook_bindings.StageOutputSync("Stage Output", None, None, cook_bindings.NO_STAGE)]
    assert bindings.in_scene(_scene()) == []
    assert nodes["output"].binding_id == ""
    assert result.node_reports["Stage Output"].diagnostics  # the cook's own diagnostic says why


def test_a_stage_output_that_loses_its_stage_keeps_its_binding_and_display(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output")
    _cook(tree)
    handle = _handle(bindings, nodes["Stage Output"])
    tree.links.remove(nodes["Stage Output"].inputs["Layer"].links[0])
    synchronized = _cook(tree)["Stage Output"]
    assert synchronized == cook_bindings.StageOutputSync(
        "Stage Output", handle.binding_id, None, cook_bindings.NO_STAGE
    )
    assert handle.live_stage() is None  # released
    assert bindings.in_scene(_scene()) == [handle]
    assert _displayed(handle) == ["Chair"]


def test_the_report_names_each_binding_and_its_result(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output")
    result = cook_panel.cook_tree(tree)
    synchronized = cook_bindings.synchronize_stage_outputs(tree, result)
    report = cook_panel.cook_report(tree, result, synchronized, with_tree_layer=False)
    binding_id = _handle(bindings, nodes["Stage Output"]).binding_id
    assert f"--- Bindings ---\n  Stage Output 'Stage Output', {binding_id}: success" in report


def test_a_cook_pushes_an_undo_step_for_each_stage_output_it_changes(bindings: Bindings) -> None:
    # Each synchronization that publishes pushes its own step; one that writes nothing pushes none (UNDO-10). Background
    # mode pushes no steps, so the test records the pushes the synchronizations ask for.
    del bindings
    tree, nodes = _cube_tree("Stage Output", "Stage Output.001")
    with patch("proscenium_sync.bindings.binding_service._push_undo") as push:
        _cook(tree)
        assert push.call_count == 2
        push.reset_mock()
        _cook(tree)  # nothing changed
        assert push.call_count == 0
        nodes["create"].inputs["Name"].default_value = "Table"
        _cook(tree)
        assert push.call_count == 2


def test_a_raise_for_one_stage_output_leaves_the_others_synchronized(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output", "Stage Output.001")
    create_binding = bindings.create_binding

    def failing_first(scene: bpy.types.Scene, *, name: str) -> BindingHandle:
        if name == "Tree Stage Output":
            raise RuntimeError("The binding index can't be read")
        return create_binding(scene, name=name)

    with patch.object(bindings, "create_binding", side_effect=failing_first):
        synchronized = _cook(tree)
    failed = synchronized["Stage Output"]
    assert failed == cook_bindings.StageOutputSync(
        "Stage Output", None, None, raised="RuntimeError: The binding index can't be read"
    )
    assert failed.failed
    assert cook_bindings.sync_report_lines([failed]) == [
        "  Stage Output 'Stage Output', no binding: raised RuntimeError: The binding index can't be read"
    ]
    handle = _handle(bindings, nodes["Stage Output.001"])
    assert synchronized["Stage Output.001"].result is not None
    assert synchronized["Stage Output.001"].result.state is ResultState.SUCCESS
    assert _displayed(handle) == ["Chair"]
