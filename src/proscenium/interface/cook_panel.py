"""The cook panel in the node editor's sidebar: a button that cooks the edited tree and prints what it gives.

Each cook writes the tree into a scratch layer and moves it into the root layer of a stage kept for that tree, which
the tree's TreeCook holds, so the cook's state, and the stages it returns, last between cooks (docs/plans/cook-module.md
"Input"). The kept cooks are keyed by the tree's session UID and hold no Blender data; loading a file drops them. The
active Viewer is the one the tree's Viewer dropdown names. The tree's diagnostics, each node's report, and each
stage the cook returns, as its root layer, are printed to the console. Nothing is handed to a binding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, override

import bpy
from pxr import Sdf, Usd

import proscenium_cook

from . import cook_node_types, cook_tree_layer

if TYPE_CHECKING:
    from collections.abc import Iterable

    from bpy.stub_internal.rna_enums import OperatorReturnItems


@dataclass(slots=True)
class KeptCook:
    """A tree's stage and the cook that holds it, with the base directory the cook was made with."""

    tree_stage: Usd.Stage
    tree_cook: proscenium_cook.TreeCook
    base_directory: str | None


_kept_cooks: dict[int, KeptCook] = {}


def cook_tree(tree: bpy.types.NodeTree) -> proscenium_cook.CookResult:
    """Cook tree with its active Viewer, writing it into its kept stage first."""
    kept = _kept_cook(tree)
    scratch = Sdf.Layer.CreateAnonymous("cook_tree")
    cook_tree_layer.write_tree_layer(tree, scratch)
    kept.tree_stage.GetRootLayer().TransferContent(scratch)
    return kept.tree_cook.cook(active_viewer(tree))


def active_viewer(tree: bpy.types.NodeTree) -> str | None:
    """The node ID the tree's Viewer dropdown names, else None.

    A name that's no longer a Viewer's, after a delete or a rename, is still given, so the cook warns unknown-viewer.
    """
    return getattr(tree, cook_node_types.VIEWER_PROPERTY) or None


def tree_stage(tree: bpy.types.NodeTree) -> Usd.Stage | None:
    """The stage holding the tree's layer as last cooked, or None before its first cook."""
    kept = _kept_cooks.get(tree.session_uid)
    return kept.tree_stage if kept is not None else None


def forget_cooks() -> None:
    """Drop every kept cook, as loading a file does."""
    _kept_cooks.clear()


def cook_report(tree: bpy.types.NodeTree, result: proscenium_cook.CookResult, *, with_tree_layer: bool) -> str:
    """What a cook gave, as the console shows it."""
    viewer = active_viewer(tree)
    lines = [f"=== Proscenium cook of {tree.name!r}, Viewer {viewer!r} ==="]
    if with_tree_layer and (stage := tree_stage(tree)) is not None:
        lines += ["--- Tree layer ---", stage.GetRootLayer().ExportToString()]
    lines.append("--- Tree diagnostics ---")
    lines += _diagnostic_lines(result.tree_diagnostics) or ["  (none)"]
    lines.append("--- Node reports ---")
    for node_id, report in sorted(result.node_reports.items()):
        lines.append(f"  {node_id!r}:")
        lines += [f"  {line}" for line in _diagnostic_lines(report.diagnostics)]
        for key, value in sorted(report.report_data.items()):
            lines.append(f"      {key}: {value!r}")
    if not result.node_reports:
        lines.append("  (none)")
    for node_id, stage in sorted(result.stage_outputs.items()):
        lines += [f"--- Stage Output {node_id!r} ---", _stage_text(stage)]
    if not result.stage_outputs:
        lines.append("--- No Stage Output has a stage ---")
    if result.viewer_stage is not None:
        lines += [f"--- Viewer {viewer!r} ---", _stage_text(result.viewer_stage)]
    else:
        lines.append(f"--- Viewer {viewer!r} has no stage ---")
    return "\n".join(lines)


def diagnostic_counts(result: proscenium_cook.CookResult) -> tuple[int, int]:
    """The cook's errors and warnings, the tree's and every node's."""
    diagnostics = [*result.tree_diagnostics]
    for report in result.node_reports.values():
        diagnostics += report.diagnostics
    errors = sum(diagnostic.severity == proscenium_cook.Severity.ERROR for diagnostic in diagnostics)
    return errors, len(diagnostics) - errors


class PROSCENIUM_OT_cook_tree(bpy.types.Operator):  # noqa: N801 - Blender's operator naming
    """Cook the edited tree, and print its diagnostics and stages to the console."""

    bl_idname = "proscenium.cook_tree"
    bl_label = "Cook"
    bl_options = {"REGISTER"}  # noqa: RUF012 - Blender's operator field; no UNDO, as it writes no Blender data

    @classmethod
    @override
    def poll(cls, context: Any) -> bool:
        """Only in a node editor showing a cook tree."""
        return _edited_tree(context) is not None

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        """Cook, print, and report the diagnostic counts."""
        tree = _edited_tree(context)
        assert tree is not None  # poll
        result = cook_tree(tree)
        with_tree_layer = getattr(tree, cook_node_types.PRINT_TREE_LAYER_PROPERTY)
        print(cook_report(tree, result, with_tree_layer=with_tree_layer))
        errors, warnings = diagnostic_counts(result)
        stages = len(result.stage_outputs) + (result.viewer_stage is not None)
        self.report({"INFO"}, f"Cooked {stages} stage(s): {errors} error(s), {warnings} warning(s); see the console")
        return {"FINISHED"}


class PROSCENIUM_PT_cook_tree(bpy.types.Panel):  # noqa: N801 - Blender's panel naming
    """The cook button, whether it prints the tree's layer, and which Viewer it cooks."""

    bl_idname = "PROSCENIUM_PT_cook_tree"
    bl_label = "Cook"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "Proscenium"

    @classmethod
    @override
    def poll(cls, context: Any) -> bool:
        """Only in a node editor showing a cook tree."""
        return _edited_tree(context) is not None

    @override
    def draw(self, context: Any) -> None:
        """The cook button, the checkbox for printing the tree's layer, and the Viewer dropdown."""
        tree = _edited_tree(context)
        assert tree is not None  # poll
        layout: Any = self.layout
        layout.operator(PROSCENIUM_OT_cook_tree.bl_idname, icon="PLAY")
        layout.prop(tree, cook_node_types.PRINT_TREE_LAYER_PROPERTY)
        layout.prop(tree, cook_node_types.VIEWER_PROPERTY, icon="HIDE_OFF")
        viewer = active_viewer(tree)
        if viewer is not None and viewer not in cook_node_types.viewer_names(tree):
            layout.label(text=f"No Viewer is named {viewer!r}", icon="ERROR")


CLASSES = (PROSCENIUM_OT_cook_tree, PROSCENIUM_PT_cook_tree)


def _edited_tree(context: Any) -> bpy.types.NodeTree | None:
    space: Any = context.space_data
    tree = getattr(space, "edit_tree", None)
    return tree if tree is not None and tree.bl_idname == cook_node_types.TREE_IDNAME else None


def _kept_cook(tree: bpy.types.NodeTree) -> KeptCook:
    """The tree's kept cook, made again when the base directory for // paths has changed."""
    base_directory = bpy.path.abspath("//") if bpy.data.filepath else None
    kept = _kept_cooks.get(tree.session_uid)
    if kept is None:
        stage = Usd.Stage.CreateInMemory()
        kept = KeptCook(stage, proscenium_cook.TreeCook(stage, base_directory), base_directory)
    elif kept.base_directory != base_directory:
        kept = KeptCook(kept.tree_stage, proscenium_cook.TreeCook(kept.tree_stage, base_directory), base_directory)
    _kept_cooks[tree.session_uid] = kept
    return kept


def _diagnostic_lines(diagnostics: Iterable[proscenium_cook.NodeDiagnostic]) -> list[str]:
    lines = []
    for diagnostic in diagnostics:
        where = f" (at {diagnostic.source_path})" if diagnostic.source_path else ""
        lines.append(f"    {diagnostic.severity.value} {diagnostic.code.value}: {diagnostic.message}{where}")
    return lines


def _stage_text(stage: Usd.Stage) -> str:
    """The stage's root layer, with its identifier: a zone's layer, or a file's, without what it composes."""
    root_layer = stage.GetRootLayer()
    return f"(root layer {root_layer.identifier})\n{root_layer.ExportToString()}"
