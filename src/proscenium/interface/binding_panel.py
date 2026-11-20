"""The binding panel: an add button, then the scene's bindings, each with its state and its buttons (M7 plan, F2).

In the 3D view's sidebar, Proscenium tab. The add button picks a USD file, opens its stage, and creates a binding on the
scene, named for the file, with the stage attached. Its operator declares UNDO, since creating a binding pushes no undo
step of its own; undoing it keeps the attachment, so redo brings the binding back attached. Each draw lists the scene's
bindings with one call (Bindings.binding_statuses): each one's name, whether a stage is attached, whether its display is
published and may be out of date, how its last attempt ended, or why it can't be used. The synchronize button
synchronizes at the scene's current frame. The remove button removes the binding (Bindings.remove_binding), its
managed content and its configuration, so one left behind needn't be deleted by hand. A binding that can't be used has
neither button, since both would refuse it; the row says why. A binding with copies (BindingStatus.has_copies) has no
remove button either, since removal refuses it while its copies' records remain; the row says so. Neither operator
declares UNDO, since the API pushes the synchronization's and the removal's undo steps.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import bpy
from pxr import Tf, Usd

import proscenium_sync

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias


def state_text(status: proscenium_sync.BindingStatus) -> str:
    """The binding's state in a few words."""
    if not status.published:
        return "Not synchronized"
    shown = "May be out of date" if status.possibly_out_of_date else "Up to date"
    if status.last_attempt is proscenium_sync.ResultState.FATAL_FAILURE:
        return f"{shown}; last attempt failed"
    return shown


def draw_bindings(layout: Any, scene: bpy.types.Scene) -> None:
    """The add button, then each binding: its name and attachment, its state or why it can't be used, and buttons."""
    layout.operator(PROSCENIUM_OT_add_binding.bl_idname, icon="ADD")
    statuses = proscenium_sync.BINDINGS.binding_statuses(scene)
    if not statuses:
        layout.label(text="No bindings")
        return
    for status in statuses:
        box = layout.box()
        row = box.row()
        row.label(text=status.name or status.binding_id, icon="LINKED" if status.attached else "UNLINKED")
        if status.refusal is not None:  # both buttons would refuse it
            box.label(text=status.refusal, icon="ERROR")
            continue
        synchronize = row.operator(PROSCENIUM_OT_synchronize.bl_idname, text="", icon="FILE_REFRESH")
        synchronize.binding_id = status.binding_id
        box.label(text=state_text(status))
        if status.has_copies:  # removal would refuse it
            box.label(text="Has copies, so it can't be removed", icon="INFO")
            continue
        remove = row.operator(PROSCENIUM_OT_remove_binding.bl_idname, text="", icon="X")
        remove.binding_id = status.binding_id


class PROSCENIUM_OT_add_binding(bpy.types.Operator):  # noqa: N801 - Blender's operator naming
    """Create a binding on the scene with a USD file's stage attached."""

    bl_idname = "proscenium.add_binding"
    bl_label = "Add Binding"
    bl_options = {"REGISTER", "UNDO"}  # noqa: RUF012 - Blender's operator field; creating a binding pushes no step
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # ty: ignore[invalid-type-form]
    filter_glob: bpy.props.StringProperty(  # ty: ignore[invalid-type-form]
        default="*.usd;*.usda;*.usdc;*.usdz", options={"HIDDEN"}
    )

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        # The stage opens first, so a file that doesn't open leaves no binding behind.
        try:
            stage = Usd.Stage.Open(self.filepath)
        except Tf.ErrorException as error:
            self.report({"ERROR"}, f"Can't open {self.filepath}: {error}")
            return {"CANCELLED"}
        if stage is None:
            self.report({"ERROR"}, f"Can't open {self.filepath}")
            return {"CANCELLED"}
        handle = proscenium_sync.BINDINGS.create_binding(context.scene, name=Path(self.filepath).stem)
        result = handle.attach(stage)
        if result.state is proscenium_sync.ResultState.FATAL_FAILURE:
            message = result.diagnostics[0].message if result.diagnostics else "Attaching the stage failed"
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        return {"FINISHED"}


class PROSCENIUM_OT_synchronize(bpy.types.Operator):  # noqa: N801 - Blender's operator naming
    """Synchronize the binding at the scene's current frame."""

    bl_idname = "proscenium.synchronize"
    bl_label = "Synchronize"
    bl_options = {"REGISTER"}  # noqa: RUF012 - Blender's operator field; no UNDO, as the API pushes the step
    binding_id: bpy.props.StringProperty()  # ty: ignore[invalid-type-form]

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        result = proscenium_sync.BINDINGS.synchronize(self.binding_id)
        if result.state is proscenium_sync.ResultState.FATAL_FAILURE:
            message = result.diagnostics[0].message if result.diagnostics else "Synchronization failed"
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        self.report({"INFO"}, f"Synchronized: {result.state.value}")
        return {"FINISHED"}


class PROSCENIUM_OT_remove_binding(bpy.types.Operator):  # noqa: N801 - Blender's operator naming
    """Remove the binding, its managed content and its configuration, keeping what anything else uses."""

    bl_idname = "proscenium.remove_binding"
    bl_label = "Remove Binding"
    bl_options = {"REGISTER"}  # noqa: RUF012 - Blender's operator field; no UNDO, as the API pushes the step
    binding_id: bpy.props.StringProperty()  # ty: ignore[invalid-type-form]

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        result = proscenium_sync.BINDINGS.remove_binding(self.binding_id)
        if result.state is proscenium_sync.ResultState.FATAL_FAILURE:  # a refusal, which changed nothing
            message = result.diagnostics[0].message if result.diagnostics else "Removing the binding failed"
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        if result.state is proscenium_sync.ResultState.COMPLETED_WITH_ISSUES:  # disposals left pending in the ledger
            issues = result.diagnostics
            self.report({"WARNING"}, f"Removed, with {len(issues)} issue(s): {issues[0].message}")
        else:
            self.report({"INFO"}, "Removed")
        return {"FINISHED"}


class PROSCENIUM_PT_bindings(bpy.types.Panel):  # noqa: N801 - Blender's panel naming
    """The scene's bindings."""

    bl_label = "Bindings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Proscenium"

    @override
    def draw(self, context: Any) -> None:
        draw_bindings(self.layout, context.scene)


CLASSES = (PROSCENIUM_OT_add_binding, PROSCENIUM_OT_synchronize, PROSCENIUM_OT_remove_binding, PROSCENIUM_PT_bindings)
