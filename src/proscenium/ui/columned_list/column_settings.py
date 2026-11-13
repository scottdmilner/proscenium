"""A list's column settings, as its settings popover draws them: each column's eye, title, and width."""

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
        if column.units_property:
            width.prop(properties, column.units_property)
        else:
            width.label(text="")
