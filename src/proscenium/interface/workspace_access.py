"""The Proscenium workspace: an operator that adds it to the file, a top bar button, and a workspace tabs' menu entry.

The workspace's layout is kept in the extension's workspace/proscenium.blend, which the operator appends and activates.
An appended workspace's tab goes last; a file that already has a workspace by that name activates it where it is
instead, so the operator never makes a second copy. The button is at the start of the top bar's right region, before
the scene and view layer, while the file has no Proscenium workspace; once it has one, that workspace's own tab takes
the button's place.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import bpy

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

WORKSPACE_NAME = "Proscenium"
WORKSPACE_PATH = Path(__file__).parent.parent / "workspace" / "proscenium.blend"


class PROSCENIUM_OT_add_workspace(bpy.types.Operator):  # noqa: N801 - Blender's operator naming
    """Add the Proscenium workspace to the file and switch to it."""

    bl_idname = "proscenium.add_workspace"
    bl_label = "Proscenium"
    # No UNDO: workspaces and their switching are outside Blender's undo.

    @classmethod
    @override
    def poll(cls, context: Any) -> bool:
        """Whether there is a window to show the workspace in."""
        return context.window is not None

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        """Activate the file's Proscenium workspace, appending it from the extension's file first if there is none."""
        # Blender switches the window's workspace when it next handles events, not on assignment.
        context.window.workspace = find_or_append_workspace()
        return {"FINISHED"}


def find_or_append_workspace() -> bpy.types.WorkSpace:
    """The file's Proscenium workspace, appended from the extension's file if the file has none."""
    existing = bpy.data.workspaces.get(WORKSPACE_NAME)
    if existing is not None:
        return existing
    with bpy.data.libraries.load(str(WORKSPACE_PATH)) as (_source, target):  # ty: ignore[invalid-context-manager] - stubs
        target.workspaces = [WORKSPACE_NAME]
    [workspace] = target.workspaces  # the appended datablock, renamed if the file has a workspace by its name
    # The tabs follow an order Python can't set, which the operator moves the context's workspace to the end of.
    override: Any = bpy.context.temp_override(workspace=workspace)  # the stubs miss its context manager methods
    with override:
        bpy.ops.workspace.reorder_to_back()
    return workspace  # ty: ignore[invalid-return-type] - the stubs type the loaded list as names


def draw_top_bar_button(header: Any, context: Any) -> None:
    """The operator's button before the scene and view layer, in the top bar's right region, while the file needs it."""
    # The top bar's draw runs once per region; the left one holds the menus and the tabs.
    if context.region.alignment != "RIGHT":
        return
    if WORKSPACE_NAME in bpy.data.workspaces:
        return
    header.layout.operator(PROSCENIUM_OT_add_workspace.bl_idname, text="Proscenium Workspace", icon="ADD")


def draw_menu_entry(menu: Any, _context: Any) -> None:
    """The operator's entry at the end of the workspace tabs' menu."""
    menu.layout.separator()
    menu.layout.operator(PROSCENIUM_OT_add_workspace.bl_idname, text="Add Proscenium Workspace", icon="WORKSPACE")


CLASSES = (PROSCENIUM_OT_add_workspace,)


def register() -> None:
    """Add the top bar button and the workspace tabs' menu entry; interface_registration registers CLASSES."""
    # Prepended, so it's drawn before the scene and view layer.
    bpy.types.TOPBAR_HT_upper_bar.prepend(draw_top_bar_button)  # ty: ignore[invalid-argument-type]
    bpy.types.TOPBAR_MT_workspace_menu.append(draw_menu_entry)  # ty: ignore[invalid-argument-type]


def unregister() -> None:
    """Remove the top bar button and the menu entry."""
    bpy.types.TOPBAR_MT_workspace_menu.remove(draw_menu_entry)  # ty: ignore[invalid-argument-type]
    bpy.types.TOPBAR_HT_upper_bar.remove(draw_top_bar_button)  # ty: ignore[invalid-argument-type]
