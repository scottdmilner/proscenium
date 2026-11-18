"""The binding panel: the scene's bindings, each with its state and a synchronize button (M7 plan, F2).

In the 3D view's sidebar, Proscenium tab. Each draw lists the scene's bindings with one call
(Bindings.binding_statuses): each one's name, whether a stage is attached, whether its display is published and may be
out of date, how its last attempt ended, or why it can't be used. The synchronize button synchronizes at the scene's
current frame; its operator declares no UNDO, since the API pushes the synchronization's undo step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy

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
    """Each of the scene's bindings: its name and attachment, then its state or why it can't be used, and a button."""
    statuses = proscenium_sync.BINDINGS.binding_statuses(scene)
    if not statuses:
        layout.label(text="No bindings")
        return
    for status in statuses:
        box = layout.box()
        row = box.row()
        row.label(text=status.name or status.binding_id, icon="LINKED" if status.attached else "UNLINKED")
        if status.refusal is not None:
            box.label(text=status.refusal, icon="ERROR")
            continue
        button = row.operator(PROSCENIUM_OT_synchronize.bl_idname, text="", icon="FILE_REFRESH")
        button.binding_id = status.binding_id
        box.label(text=state_text(status))


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


class PROSCENIUM_PT_bindings(bpy.types.Panel):  # noqa: N801 - Blender's panel naming
    """The scene's bindings."""

    bl_label = "Bindings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Proscenium"

    @override
    def draw(self, context: Any) -> None:
        draw_bindings(self.layout, context.scene)


CLASSES = (PROSCENIUM_OT_synchronize, PROSCENIUM_PT_bindings)
