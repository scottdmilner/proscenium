"""The Type column: a row's prim's type name, or a dash for a typeless prim."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....columned_list import column_layout

if TYPE_CHECKING:
    import bpy

    from ....widget_model.prim_details import RowDetails


def _draw_cell(layout: bpy.types.UILayout, details: RowDetails) -> None:
    layout.label(text=details.type_name or "-")


TYPE_COLUMN: column_layout.Column[RowDetails] = column_layout.Column(
    "Type", "show_type_column", _draw_cell, "type_column_units"
)
