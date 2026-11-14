"""Copying to the clipboard from a widget's rows: `CopyUsdPath`, which copies a prim's or a property's path.

Internal, and it changes no data, so it pushes no undo step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias


class CopyUsdPath(bpy.types.Operator):
    """Copy a USD path to the clipboard."""

    bl_idname = "proscenium.copy_usd_path"
    bl_label = "Copy Path"
    bl_options = {"INTERNAL"}

    usd_path: bpy.props.StringProperty()  # ty: ignore[invalid-type-form]

    @override
    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        return f"Copy {properties.usd_path}"

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        context.window_manager.clipboard = self.usd_path
        self.report({"INFO"}, f"Copied {self.usd_path}")
        return {"FINISHED"}


# In registration order.
CLASSES = (CopyUsdPath,)
