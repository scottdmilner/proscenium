"""The Children column: how many children a row's prim has, as its expanded row lists them."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .column_layout import Column

if TYPE_CHECKING:
    import bpy

    from ...prim_tree import RowDetails


def _draw_cell(layout: bpy.types.UILayout, details: RowDetails) -> None:
    layout.label(text=str(details.child_count) if details.has_children else "")  # a leaf's blank, as its chevron


CHILDREN_COLUMN = Column(
    "Children",
    "show_children_column",
    _draw_cell,
    "children_column_units",
    header_icon="CON_CHILDOF",
    alignment="RIGHT",
)
