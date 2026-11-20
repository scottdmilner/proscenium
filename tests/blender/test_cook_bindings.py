"""The temporary UI's cook into bindings: each Stage Output's stage handed to a binding of its own and synchronized.

Each test builds a tree through bpy as a user would, cooks it as the Cook operator does (cook_panel.cook_tree, then
cook_bindings.synchronize_stage_outputs and remove_unnamed_bindings), and reads the scene's bindings and their
displays. Expected values come from how the test built its tree and from the stage-output-bindings plan. Undo steps are
pushed only outside background mode, which the bpy wheel always is, so the undo test patches the API's
_undo_steps_enabled.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import bpy

from proscenium.interface import cook_bindings, cook_node_types, cook_panel
from proscenium_sync.bindings import binding_service as api
from proscenium_sync.results import DiagnosticCode, ResultState
from support import undo
from support.blend import prim_name, save_and_reopen
from support.destinations import destination
from support.recording_layout import RecordingLayout

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

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


def _cook_all(tree: Any) -> tuple[dict[str, cook_bindings.StageOutputSync], list[cook_bindings.BindingRemoval]]:
    """Cook tree, synchronize its Stage Outputs, and remove the bindings none names, as the Cook operator does.

    What each Stage Output did, by node name, and the removals.
    """
    result = cook_panel.cook_tree(tree)
    synchronized = {sync.node_id: sync for sync in cook_bindings.synchronize_stage_outputs(tree, result)}
    return synchronized, cook_bindings.remove_unnamed_bindings(tree)


def _cook(tree: Any) -> dict[str, cook_bindings.StageOutputSync]:
    """_cook_all's synchronizations."""
    return _cook_all(tree)[0]


def _removals(tree: Any) -> list[cook_bindings.BindingRemoval]:
    """_cook_all's removals."""
    return _cook_all(tree)[1]


def _record(tree: Any) -> list[str]:
    """The bindings the tree's record lists."""
    return sorted(item.name for item in getattr(tree, cook_node_types.MADE_BINDINGS_PROPERTY))


def _removed(removal: cook_bindings.BindingRemoval) -> bool:
    """Whether the removal committed with no issues."""
    return removal.result is not None and removal.result.state is ResultState.SUCCESS


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
    assert _record(tree) == named
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
    with patch.object(bindings, "set_settings", wraps=bindings.set_settings) as set_settings:
        _cook(tree)  # unchanged, so not written again: each write is a new record revision
    set_settings.assert_not_called()


def test_a_copied_trees_stage_output_gets_its_own_binding(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output")
    _cook(tree)
    original = _handle(bindings, nodes["Stage Output"])
    copy = tree.copy()
    assert _record(copy) == []  # Blender copies the record whole; the copy callback drops the original's binding
    assert _removals(copy) == []
    copied = _handle(bindings, copy.nodes["Stage Output"])
    assert copied != original
    assert nodes["Stage Output"].binding_id == original.binding_id
    assert sorted(bindings.in_scene(_scene()), key=str) == sorted([original, copied], key=str)
    assert _displayed(original) == _displayed(copied) == ["Chair"]
    assert _record(tree) == [original.binding_id]
    assert _record(copy) == [copied.binding_id]


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
    removals = [cook_bindings.BindingRemoval("gone", None)]
    report = cook_panel.cook_report(tree, result, synchronized, removals, with_tree_layer=False)
    binding_id = _handle(bindings, nodes["Stage Output"]).binding_id
    assert f"--- Bindings ---\n  Stage Output 'Stage Output', {binding_id}: success" in report
    assert report.endswith("--- Removed bindings ---\n  gone: already gone")


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


def test_deleting_a_stage_output_removes_its_binding_on_the_next_cook_and_keeps_the_others(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output", "Stage Output.001")
    _cook(tree)
    deleted, kept = _handle(bindings, nodes["Stage Output"]), _handle(bindings, nodes["Stage Output.001"])
    chairs = sorted(obj.name for obj in destination(deleted).all_objects)
    tree.nodes.remove(nodes["Stage Output"])
    [removal] = _removals(tree)
    assert removal.binding_id == deleted.binding_id
    assert _removed(removal)
    assert bindings.in_scene(_scene()) == [kept]
    assert "Tree Stage Output" not in bpy.data.collections  # the destination, which held nothing else
    assert not set(chairs) & {obj.name for obj in bpy.data.objects}
    assert _displayed(kept) == ["Chair"]
    assert _record(tree) == [kept.binding_id]
    assert _removals(tree) == []


def test_undo_restores_a_deleted_stage_output_and_its_binding(
    bindings: Bindings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # UNDO-08: the removal is one undo step, after the delete's own, which a window's delete operator pushes.
    undo.require_global_undo()
    monkeypatch.setattr(api, "_undo_steps_enabled", lambda: True)
    tree, nodes = _cube_tree("Stage Output", "Stage Output.001")
    _cook(tree)
    deleted, kept = _handle(bindings, nodes["Stage Output"]), _handle(bindings, nodes["Stage Output.001"])
    undo.push("base")
    tree.nodes.remove(nodes["Stage Output"])
    undo.push("Delete")
    assert _removed(_removals(tree)[0])
    undo.undo()
    tree = bpy.data.node_groups["Tree"]
    assert sorted(bindings.in_scene(_scene()), key=str) == sorted([deleted, kept], key=str)
    assert "Stage Output" not in tree.nodes
    assert _record(tree) == sorted([deleted.binding_id, kept.binding_id])
    assert _displayed(deleted) == ["Chair"]
    undo.undo()
    restored: Any = bpy.data.node_groups["Tree"].nodes["Stage Output"]
    assert restored.binding_id == deleted.binding_id


def test_changing_a_stage_outputs_scene_moves_its_binding(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output")
    _cook(tree)
    old = _handle(bindings, nodes["Stage Output"])
    other = bpy.data.scenes.new("Other")
    nodes["Stage Output"].scene = other
    synchronized, [removal] = _cook_all(tree)
    [moved] = bindings.in_scene(other)
    assert synchronized["Stage Output"].binding_id == nodes["Stage Output"].binding_id == moved.binding_id
    assert moved != old
    assert (removal.binding_id, _removed(removal)) == (old.binding_id, True)
    assert bindings.in_scene(_scene()) == []
    assert _displayed(moved) == ["Chair"]
    assert _record(tree) == [moved.binding_id]


def test_clearing_a_stage_outputs_scene_removes_its_binding(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output")
    _cook(tree)
    binding_id = nodes["Stage Output"].binding_id
    nodes["Stage Output"].scene = None
    [removal] = _removals(tree)
    assert (removal.binding_id, _removed(removal)) == (binding_id, True)
    assert bindings.in_scene(_scene()) == []
    assert _record(tree) == []


def test_deleting_a_whole_tree_leaves_its_bindings(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output")
    _cook(tree)
    handle = _handle(bindings, nodes["Stage Output"])
    other, _ = _cube_tree()
    bpy.data.node_groups.remove(tree)
    assert _removals(other) == []
    assert bindings.in_scene(_scene()) == [handle]
    assert _displayed(handle) == ["Chair"]


def test_deleting_the_original_of_a_copied_tree_leaves_its_bindings(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output")
    _cook(tree)
    original = _handle(bindings, nodes["Stage Output"])
    copy = tree.copy()
    bpy.data.node_groups.remove(tree)
    assert _removals(copy) == []
    copied = _handle(bindings, copy.nodes["Stage Output"])
    assert sorted(bindings.in_scene(_scene()), key=str) == sorted([original, copied], key=str)
    assert _displayed(original) == ["Chair"]


def test_a_copied_tree_keeps_the_bindings_the_original_was_still_to_remove(bindings: Bindings) -> None:
    # The deleted node fires no copy callback, so its binding stays in the copy's record, and the copy's cook
    # removes it.
    tree, nodes = _cube_tree("Stage Output", "Stage Output.001")
    _cook(tree)
    deleted, kept = _handle(bindings, nodes["Stage Output"]), _handle(bindings, nodes["Stage Output.001"])
    tree.nodes.remove(nodes["Stage Output"])
    copy = tree.copy()
    assert _record(copy) == [deleted.binding_id]
    [removal] = _removals(copy)
    assert (removal.binding_id, _removed(removal)) == (deleted.binding_id, True)
    assert kept in bindings.in_scene(_scene())
    assert _removals(tree) == [cook_bindings.BindingRemoval(deleted.binding_id, None)]  # already gone


def test_a_duplicate_within_a_tree_keeps_the_trees_record(bindings: Bindings) -> None:
    # Background mode can't run Blender's duplicate, so the callback is called as it would call it: the original is in
    # the same tree as the new node.
    tree, nodes = _cube_tree("Stage Output")
    _cook(tree)
    binding_id = nodes["Stage Output"].binding_id
    duplicate = _node(tree, "StageOutput", "Stage Output.001")
    duplicate.binding_id = binding_id  # Blender copies the node's properties before the callback
    type(duplicate).copy(duplicate, nodes["Stage Output"])
    assert duplicate.binding_id == ""
    assert _record(tree) == [binding_id]
    assert _removals(tree) == []


def test_two_stage_outputs_naming_one_binding_leave_it_to_the_first(bindings: Bindings) -> None:
    # As a script, an appended tree, or a library override can leave them; the copy callback can't clear them.
    tree, nodes = _cube_tree("Stage Output", "Stage Output.001")
    _cook(tree)
    kept = _handle(bindings, nodes["Stage Output"])
    lost = _handle(bindings, nodes["Stage Output.001"])
    nodes["Stage Output.001"].binding_id = kept.binding_id
    synchronized, [removal] = _cook_all(tree)
    second = synchronized["Stage Output.001"]
    assert synchronized["Stage Output"] == cook_bindings.StageOutputSync(
        "Stage Output", kept.binding_id, synchronized["Stage Output"].result
    )
    assert second.shared_with == "Stage Output"
    assert second.binding_id == nodes["Stage Output.001"].binding_id
    assert second.binding_id not in {kept.binding_id, lost.binding_id}
    assert (removal.binding_id, _removed(removal)) == (lost.binding_id, True)  # nothing names it now
    assert cook_bindings.sync_report_lines([second]) == [
        f"  Stage Output 'Stage Output.001', {second.binding_id}: success",
        "    named the binding Stage Output 'Stage Output' keeps, so it has its own",
    ]
    assert _displayed(kept) == _displayed(_handle(bindings, nodes["Stage Output.001"])) == ["Chair"]
    assert all(sync.shared_with is None for sync in _cook(tree).values())


def test_a_binding_already_gone_is_dropped_from_the_record(bindings: Bindings) -> None:
    # Deleting the destination removes the binding with its records, so the next cook makes another and drops the first.
    tree, nodes = _cube_tree("Stage Output")
    _cook(tree)
    gone = nodes["Stage Output"].binding_id
    bpy.data.collections.remove(bpy.data.collections["Tree Stage Output"])
    synchronized, removals = _cook_all(tree)
    assert removals == [cook_bindings.BindingRemoval(gone, None)]
    assert cook_bindings.removal_report_lines(removals) == [f"  {gone}: already gone"]
    assert synchronized["Stage Output"].binding_id != gone
    assert _record(tree) == [nodes["Stage Output"].binding_id]


def test_a_refused_removal_keeps_the_binding_in_the_record(bindings: Bindings) -> None:
    # A binding with copies is refused, changing nothing, so the next cook tries again.
    tree, nodes = _cube_tree("Stage Output")
    _cook(tree)
    handle = _handle(bindings, nodes["Stage Output"])
    copy = bpy.data.collections["Tree Stage Output"].copy()
    _scene().collection.children.link(copy)
    tree.nodes.remove(nodes["Stage Output"])
    [removal] = _removals(tree)
    assert removal.failed
    assert removal.result is not None
    assert [d.code for d in removal.result.diagnostics] == [DiagnosticCode.COPIED_BINDING]
    assert bindings.in_scene(_scene()) == [handle]
    assert _record(tree) == [handle.binding_id]
    assert [r.binding_id for r in _removals(tree)] == [handle.binding_id]


def test_a_removal_that_raises_keeps_the_binding_in_the_record(bindings: Bindings) -> None:
    tree, nodes = _cube_tree("Stage Output")
    _cook(tree)
    binding_id = nodes["Stage Output"].binding_id
    tree.nodes.remove(nodes["Stage Output"])
    with patch.object(bindings, "remove_binding", side_effect=RuntimeError("The ledger can't be written")):
        removals = _removals(tree)
    raised = "RuntimeError: The ledger can't be written"
    assert removals == [cook_bindings.BindingRemoval(binding_id, None, raised=raised)]
    assert removals[0].failed
    assert cook_bindings.removal_report_lines(removals) == [f"  {binding_id}: raised {raised}"]
    assert _record(tree) == [binding_id]
