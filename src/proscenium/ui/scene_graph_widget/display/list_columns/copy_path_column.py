"""The Copy Path column: a button on each row that puts its prim's path on the clipboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....columned_list import column_layout
from ....widget_resources import clipboard_operators

if TYPE_CHECKING:
    import bpy

    from ...prim_tree import RowDetails

COPY_BUTTON_WIDTH_SCALE = 1.3  # wider than its icon, so the icon's sides stay clear of the button's edges


def _draw_cell(layout: bpy.types.UILayout, details: RowDetails) -> None:
    # Embossed, so it reads as a button. Scaling a button scales its frame, not its icon, and an icon-only button
    # keeps its own width in a wider cell, so a scale is what gives the icon room inside.
    button = layout.row(align=True)
    button.scale_x = COPY_BUTTON_WIDTH_SCALE
    copy = button.operator(clipboard_operators.CopyUsdPath.bl_idname, text="", icon="DUPLICATE")
    copy.usd_path = str(details.path)


# Its header blank, as each row's button shows what the column holds; a button's width, so not resizable.
COPY_PATH_COLUMN: column_layout.Column[RowDetails] = column_layout.Column(
    "Copy Path",
    "show_copy_path_column",
    _draw_cell,
    fixed_units=COPY_BUTTON_WIDTH_SCALE,
    header_icon="BLANK1",
    alignment="CENTER",
)
