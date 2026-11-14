"""The Children column: how many children a row's prim has, as its expanded row lists them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....columned_list import column_layout

if TYPE_CHECKING:
    import bpy

    from ....widget_model.prim_details import RowDetails


def _draw_cell(layout: bpy.types.UILayout, details: RowDetails) -> None:
    layout.label(text=str(details.child_count) if details.has_children else "")  # a leaf's blank, as its chevron


CHILDREN_COLUMN: column_layout.Column[RowDetails] = column_layout.Column(
    "Children",
    "show_children_column",
    _draw_cell,
    "children_column_units",
    header_icon="CON_CHILDOF",
    alignment="RIGHT",
)
