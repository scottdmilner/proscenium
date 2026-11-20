"""Each Stage Output's binding: a cook hands each one's stage to it and synchronizes it (stage-output-bindings plan).

For each Stage Output in the tree, by node ID, the binding is the one its stored identifier names among its scene's
bindings (Bindings.in_scene). With none there, one is created in that scene, named for the tree and the node, and its
identifier stored on the node and in the tree's record (cook_node_types.MADE_BINDINGS_PROPERTY). The node's stage is
attached when the binding has no live stage or another one, with confirmation: the front end owns the stage, whose
anonymous root layer gets a new identifier after every reload. The node's coordinate conversion is recorded, when it
differs, then the binding synchronizes at its scene's current frame. Each synchronization that publishes pushes an undo
step of its own, so a cook pushes one per Stage Output it changes. A binding a cook creates whose synchronization fails
is in no step until the next, with the node's identifier and the record entry, since create_binding pushes none. A Stage
Output with no stage, unlinked or with a failed input, keeps its binding and its last display, and the binding is
released; the cook's own diagnostic says why. One with no scene has no binding. A call that raises for one Stage Output,
a defect or a record that can't be read, is reported as its failure, with the traceback printed, and the others still
synchronize.

Two Stage Outputs of a tree naming one binding, which a script, an appended tree, or a library override can leave
though the copy callback clears a copy's identifier, would attach their stages to it in turn. The first by name keeps
it; each later one's identifier is cleared, so it makes a binding of its own, and the report says which kept it.

After synchronizing, a cook removes each binding the tree's record lists that no Stage Output names in its own scene:
the node was deleted, or its scene changed or was cleared. A copied tree's record leaves out the bindings the original's
Stage Outputs name (cook_node_types.CookNode.copy), so the copy removes none of them, even once the original is deleted.
It keeps those the original was still to remove, its deleted nodes' and those whose removal was refused, so whichever
tree cooks first removes them. A Stage Output of any cook tree naming a binding keeps it too, as for a tree appended
from another file. A binding is dropped from the record before its removal, which pushes an undo step holding the record
without it; a removal that's refused or raises leaves it in the record, so a later cook tries again. One already gone,
its collection deleted or the binding removed in the binding UI, is just dropped. Nothing removes a binding when its
node is freed: Blender frees nodes on a file load and an undo step's reload too. Deleting a whole tree leaves its
bindings as ordinary bindings, which the binding UI can remove.
"""

from __future__ import annotations

import dataclasses
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import bpy

import proscenium_sync

from . import cook_node_types

if TYPE_CHECKING:
    import proscenium_cook

NO_SCENE = "No scene, so no binding"
NO_STAGE = "No stage, so nothing to synchronize"  # the cook's diagnostic says why


@dataclass(frozen=True, slots=True)
class StageOutputSync:
    """What a cook did with one Stage Output's binding."""

    node_id: str
    binding_id: str | None  # None while it has none: it has no scene, or has had no stage
    result: proscenium_sync.Result | None  # the first step that failed, else the synchronization's; None if none ran
    skipped: str | None = None  # why nothing ran, when nothing did
    raised: str | None = None  # the exception a call raised, which stopped this Stage Output's steps
    shared_with: str | None = None  # the Stage Output that kept the binding this one also named, so it made its own

    @property
    def failed(self) -> bool:
        """Whether creating the binding, attaching, recording the setting, or synchronizing failed or raised."""
        fatal = self.result is not None and self.result.state is proscenium_sync.ResultState.FATAL_FAILURE
        return fatal or self.raised is not None


@dataclass(frozen=True, slots=True)
class BindingRemoval:
    """What a cook did with a binding its tree made that no Stage Output names any more."""

    binding_id: str
    result: proscenium_sync.Result | None  # the removal's; None if the binding was already gone, or the call raised
    raised: str | None = None  # the exception the removal raised

    @property
    def failed(self) -> bool:
        """Whether the removal was refused or raised, so the binding stays in the tree's record."""
        refused = self.result is not None and self.result.state is proscenium_sync.ResultState.FATAL_FAILURE
        return refused or self.raised is not None


def stage_output_nodes(tree: bpy.types.NodeTree) -> list[Any]:
    """The tree's Stage Outputs, by name."""
    nodes = (
        node
        for node in tree.nodes
        if isinstance(node, cook_node_types.CookNode)
        and node.cook_definition.type_name == cook_node_types.STAGE_OUTPUT_TYPE
    )
    return sorted(nodes, key=lambda node: node.name)


def synchronize_stage_outputs(tree: bpy.types.NodeTree, cook: proscenium_cook.CookResult) -> list[StageOutputSync]:
    """Hand each Stage Output's stage from cook to its binding, and synchronize it; what was done, by node name."""
    synchronizations = []
    keepers: dict[str, str] = {}  # the Stage Output that keeps each binding, by identifier
    for node in stage_output_nodes(tree):  # by name, so the first by name keeps a binding
        binding_id = getattr(node, cook_node_types.BINDING_ID_PROPERTY)
        shared_with = keepers.get(binding_id) if binding_id else None
        if shared_with is not None:
            setattr(node, cook_node_types.BINDING_ID_PROPERTY, "")  # so it makes its own
        elif binding_id:
            keepers[binding_id] = node.name
        sync = _guarded(tree, node, cook.stage_outputs.get(node.name))
        synchronizations.append(dataclasses.replace(sync, shared_with=shared_with) if shared_with else sync)
    return synchronizations


def remove_unnamed_bindings(tree: bpy.types.NodeTree) -> list[BindingRemoval]:
    """Remove each binding tree's record lists that no Stage Output names in its scene; what was done, by identifier."""
    record = getattr(tree, cook_node_types.MADE_BINDINGS_PROPERTY)
    named = _named_bindings()
    removals = []
    for binding_id in sorted(item.name for item in record if item.name not in named):
        record.remove(record.find(binding_id))  # first, so the removal's undo step holds the record without it
        removal = _removal(binding_id)
        if removal.failed:
            record.add().name = binding_id  # a later cook tries again
        removals.append(removal)
    return removals


def sync_report_lines(synchronizations: list[StageOutputSync]) -> list[str]:
    """Each Stage Output's binding and how its synchronization ended, as the console shows them."""
    lines = []
    for sync in synchronizations:
        if sync.raised is not None:
            ending = f"raised {sync.raised}"
        elif sync.result is None:
            ending = sync.skipped
        else:
            ending = sync.result.state.value
        lines.append(f"  Stage Output {sync.node_id!r}, {sync.binding_id or 'no binding'}: {ending}")
        if sync.shared_with is not None:
            lines.append(f"    named the binding Stage Output {sync.shared_with!r} keeps, so it has its own")
        if sync.result is not None:
            lines += [f"    {d.code.value}: {d.message}" for d in sync.result.diagnostics]
    return lines or ["  (none)"]


def removal_report_lines(removals: list[BindingRemoval]) -> list[str]:
    """Each binding a cook removed, or tried to, and how its removal ended, as the console shows them."""
    lines = []
    for removal in removals:
        if removal.raised is not None:
            lines.append(f"  {removal.binding_id}: raised {removal.raised}")
            continue
        if removal.result is None:
            lines.append(f"  {removal.binding_id}: already gone")
            continue
        lines.append(f"  {removal.binding_id}: {removal.result.state.value}")
        lines += [f"    {d.code.value}: {d.message}" for d in removal.result.diagnostics]
    return lines or ["  (none)"]


def _guarded(tree: bpy.types.NodeTree, node: Any, stage: Any) -> StageOutputSync:
    """_synchronize, with a raise reported as the Stage Output's failure, so the others still synchronize."""
    try:
        return _synchronize(tree, node, stage)
    except Exception as error:  # noqa: BLE001 - the traceback is printed, and the report names the raise
        traceback.print_exc()
        binding_id = getattr(node, cook_node_types.BINDING_ID_PROPERTY) or None  # one made before the raise
        return StageOutputSync(node.name, binding_id, None, raised=f"{type(error).__name__}: {error}")


def _synchronize(tree: bpy.types.NodeTree, node: Any, stage: Any) -> StageOutputSync:
    scene = getattr(node, cook_node_types.SCENE_PROPERTY)
    if scene is None:
        return StageOutputSync(node.name, None, None, NO_SCENE)
    handle = _found(scene, getattr(node, cook_node_types.BINDING_ID_PROPERTY))
    if stage is None:  # the binding, if any, keeps its last display
        if handle is not None:
            handle.release()
        return StageOutputSync(node.name, handle.binding_id if handle is not None else None, None, NO_STAGE)
    if handle is None:
        handle = proscenium_sync.BINDINGS.create_binding(scene, name=f"{tree.name} {node.name}")
        setattr(node, cook_node_types.BINDING_ID_PROPERTY, handle.binding_id)
        # Recorded where it's made, so it's removed once no Stage Output names it, after a scene change too.
        getattr(tree, cook_node_types.MADE_BINDINGS_PROPERTY).add().name = handle.binding_id
    if handle.live_stage() != stage:
        if (attached := handle.attach(stage, confirm=True)).state is proscenium_sync.ResultState.FATAL_FAILURE:
            return StageOutputSync(node.name, handle.binding_id, attached)
    conversion = bool(node.prop_coordinateConversion)  # the definition's props:coordinateConversion
    # Written only when it changes: each write is a new record revision, which a synchronization that publishes nothing
    # leaves out of any undo step.
    if (
        handle.requested_settings().coordinate_conversion != conversion
        and (recorded := handle.set_settings(coordinate_conversion=conversion)).state
        is proscenium_sync.ResultState.FATAL_FAILURE
    ):
        return StageOutputSync(node.name, handle.binding_id, recorded)
    return StageOutputSync(node.name, handle.binding_id, handle.synchronize())


def _found(scene: bpy.types.Scene, binding_id: str) -> proscenium_sync.BindingHandle | None:
    """The scene's binding binding_id names, or None: none is stored, or it's gone, or in another scene."""
    if not binding_id:
        return None
    return next((h for h in proscenium_sync.BINDINGS.in_scene(scene) if h.binding_id == binding_id), None)


def _named_bindings() -> set[str]:
    """The bindings a Stage Output of any cook tree names in its scene, by identifier.

    A scene whose bindings can't be listed counts each binding its Stage Outputs name, so none of them is removed.
    """
    by_scene: dict[int, tuple[bpy.types.Scene, set[str]]] = {}
    for tree in bpy.data.node_groups:
        if tree.bl_idname != cook_node_types.TREE_IDNAME:
            continue
        for node in stage_output_nodes(tree):
            scene = getattr(node, cook_node_types.SCENE_PROPERTY)
            if scene is not None and (binding_id := getattr(node, cook_node_types.BINDING_ID_PROPERTY)):
                by_scene.setdefault(scene.session_uid, (scene, set()))[1].add(binding_id)
    named: set[str] = set()
    for scene, binding_ids in by_scene.values():
        try:
            in_scene = {handle.binding_id for handle in proscenium_sync.BINDINGS.in_scene(scene)}
        except Exception:  # noqa: BLE001 - the traceback is printed, and its Stage Outputs' bindings are kept
            traceback.print_exc()
            in_scene = binding_ids
        named |= binding_ids & in_scene
    return named


def _removal(binding_id: Any) -> BindingRemoval:  # the record's string, which the API takes as its BindingId
    """Remove the binding, with a raise reported as its failure, so the other removals still run."""
    try:
        return BindingRemoval(binding_id, proscenium_sync.BINDINGS.remove_binding(binding_id))
    except proscenium_sync.BindingNotFoundError:
        return BindingRemoval(binding_id, None)  # already gone
    except Exception as error:  # noqa: BLE001 - the traceback is printed, and the report names the raise
        traceback.print_exc()
        return BindingRemoval(binding_id, None, raised=f"{type(error).__name__}: {error}")
