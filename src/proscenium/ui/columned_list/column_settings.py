"""A list's settings popover: the gear that opens it, and each column's line in it: its eye, title, and width.

The popover is a header panel (`bl_space_type = "TOPBAR"`, `bl_region_type = "HEADER"`), which shows only where a
popover opens it, and reads the list's properties from a context member the gear's layout sets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import bpy

    from . import column_layout


def draw_column_settings(
    layout: bpy.types.UILayout, properties: Any, columns: tuple[column_layout.Column[Any], ...]
) -> None:
    """Draw a line per column: whether it shows, its title, and its width where it has one."""
    layout.label(text="Columns")
    for column in columns:
        row = layout.row()
        is_shown = getattr(properties, column.show_property)
        # The eye, open or closed, as the Outliner's; then the title, and the width, dimmed while hidden, for a
        # column that has one.
        eye_and_title = row.row(align=True)
        eye_and_title.prop(
            properties, column.show_property, text="", icon="HIDE_OFF" if is_shown else "HIDE_ON", emboss=False
        )
        eye_and_title.label(text=column.title)
        width = row.row()
        width.active = is_shown
        if column.units_property or column.share_property:
            width.prop(properties, column.units_property or column.share_property)
        else:
            width.label(text="")


def draw_settings_gear(layout: bpy.types.UILayout, properties: Any, panel_idname: str, context_member: str) -> None:
    """Draw the gear that opens a settings popover at a row's end, giving it the list's properties as a member."""
    settings = layout.row()
    settings.alignment = "RIGHT"
    settings.emboss = "NONE"
    settings.context_pointer_set(context_member, properties)
    settings.popover(panel_idname, text="", icon="PREFERENCES")
