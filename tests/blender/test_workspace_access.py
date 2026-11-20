"""The Proscenium workspace's operator and its top bar button, shown while the file lacks the workspace.

The operator appends the extension's workspace once, then reuses the file's copy. Expected names come from the
extension's workspace/proscenium.blend, which holds one workspace named Proscenium. The window's switch to the
workspace happens when Blender next handles events, which the bpy wheel never does, so these tests don't check it, nor
the tabs' order, which Python can't read. The button draws into a recording layout (support/recording_layout.py), with
a stand-in for the top bar's region.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import bpy

from proscenium.interface import workspace_access
from support.recording_layout import RecordingLayout

if TYPE_CHECKING:
    from types import ModuleType


def _add_workspace() -> set[str]:
    return bpy.ops.proscenium.add_workspace()  # ty: ignore[unresolved-attribute]


def test_the_workspace_file_holds_only_the_named_workspace() -> None:
    with bpy.data.libraries.load(str(workspace_access.WORKSPACE_PATH)) as (source, _target):  # ty: ignore[invalid-context-manager]
        assert list(source.workspaces) == [workspace_access.WORKSPACE_NAME]


def test_adding_appends_the_workspace_alone(extension: ModuleType) -> None:
    del extension
    assert workspace_access.WORKSPACE_NAME not in bpy.data.workspaces
    scenes = set(bpy.data.scenes.keys())
    assert _add_workspace() == {"FINISHED"}
    assert workspace_access.WORKSPACE_NAME in bpy.data.workspaces
    assert bpy.data.workspaces[workspace_access.WORKSPACE_NAME].library is None  # appended, not linked
    assert set(bpy.data.scenes.keys()) == scenes  # the workspace brings no scene with it


def test_adding_again_reuses_the_files_copy(extension: ModuleType) -> None:
    del extension
    _add_workspace()
    names = sorted(bpy.data.workspaces.keys())
    assert _add_workspace() == {"FINISHED"}
    assert sorted(bpy.data.workspaces.keys()) == names


def _drawn_button(*, alignment: str = "RIGHT") -> list[tuple[str, str]]:
    header = SimpleNamespace(layout=RecordingLayout())
    region = SimpleNamespace(alignment=alignment)
    context = SimpleNamespace(region=region)
    workspace_access.draw_top_bar_button(header, context)
    return [(drawn.idname, drawn.icon) for drawn in header.layout.operators]


def test_the_top_bar_shows_the_button_until_the_file_has_the_workspace(extension: ModuleType) -> None:
    del extension
    assert _drawn_button() == [("proscenium.add_workspace", "ADD")]
    _add_workspace()
    assert _drawn_button() == []  # the workspace's own tab takes its place


def test_the_button_is_only_in_the_right_region(extension: ModuleType) -> None:
    del extension
    assert _drawn_button(alignment="LEFT") == []  # the menus' and tabs' side


def test_the_top_bar_and_the_tabs_menu_have_their_entries_while_registered(extension: ModuleType) -> None:
    def entries() -> set[object]:
        return {
            *getattr(bpy.types.TOPBAR_HT_upper_bar.draw, "_draw_funcs", []),
            *getattr(bpy.types.TOPBAR_MT_workspace_menu.draw, "_draw_funcs", []),
        }

    ours = {workspace_access.draw_top_bar_button, workspace_access.draw_menu_entry}
    assert ours <= entries()
    # Before the top bar's own draw, so the button comes before the scene and view layer.
    assert getattr(bpy.types.TOPBAR_HT_upper_bar.draw, "_draw_funcs", [])[:1] == [workspace_access.draw_top_bar_button]
    extension.unregister()
    assert not ours & entries()
