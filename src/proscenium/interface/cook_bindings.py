"""Each Stage Output's binding: a cook hands each one's stage to it and synchronizes it (stage-output-bindings plan).

For each Stage Output in the tree, by node ID, the binding is the one its stored identifier names among its scene's
bindings (Bindings.in_scene). With none there, one is created in that scene, named for the tree and the node, and its
identifier stored on the node. The node's stage is attached when the binding has no live stage or another one, with
confirmation: the front end owns the stage, whose anonymous root layer gets a new identifier after every reload. The
node's coordinate conversion is recorded, then the binding synchronizes at its scene's current frame. Each
synchronization that publishes pushes an undo step of its own, so a cook pushes one per Stage Output it changes. A Stage
Output with no stage, unlinked or with a failed input, keeps its binding and its last display, and the binding is
released; the cook's own diagnostic says why. One with no scene has no binding. A call that raises for one Stage Output,
a defect or a record that can't be read, is reported as its failure, with the traceback printed, and the others still
synchronize.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import proscenium_sync

from . import cook_node_types

if TYPE_CHECKING:
    import bpy

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

    @property
    def failed(self) -> bool:
        """Whether creating the binding, attaching, recording the setting, or synchronizing failed or raised."""
        fatal = self.result is not None and self.result.state is proscenium_sync.ResultState.FATAL_FAILURE
        return fatal or self.raised is not None


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
    return [_guarded(tree, node, cook.stage_outputs.get(node.name)) for node in stage_output_nodes(tree)]


def sync_report_lines(synchronizations: list[StageOutputSync]) -> list[str]:
    """Each Stage Output's binding and how its synchronization ended, as the console shows them."""
    lines = []
    for sync in synchronizations:
        binding = sync.binding_id or "no binding"
        if sync.raised is not None:
            lines.append(f"  Stage Output {sync.node_id!r}, {binding}: raised {sync.raised}")
            continue
        if sync.result is None:
            lines.append(f"  Stage Output {sync.node_id!r}, {binding}: {sync.skipped}")
            continue
        lines.append(f"  Stage Output {sync.node_id!r}, {binding}: {sync.result.state.value}")
        lines += [f"    {d.code.value}: {d.message}" for d in sync.result.diagnostics]
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
    if handle.live_stage() != stage:
        if (attached := handle.attach(stage, confirm=True)).state is proscenium_sync.ResultState.FATAL_FAILURE:
            return StageOutputSync(node.name, handle.binding_id, attached)
    conversion = bool(node.prop_coordinateConversion)  # the definition's props:coordinateConversion
    if (recorded := handle.set_settings(coordinate_conversion=conversion)).state is (
        proscenium_sync.ResultState.FATAL_FAILURE
    ):
        return StageOutputSync(node.name, handle.binding_id, recorded)
    return StageOutputSync(node.name, handle.binding_id, handle.synchronize())


def _found(scene: bpy.types.Scene, binding_id: str) -> proscenium_sync.BindingHandle | None:
    """The scene's binding binding_id names, or None: none is stored, or it's gone, or in another scene."""
    if not binding_id:
        return None
    return next((h for h in proscenium_sync.BINDINGS.in_scene(scene) if h.binding_id == binding_id), None)
