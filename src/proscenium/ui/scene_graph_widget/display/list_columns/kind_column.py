"""The Kind column: a row's prim's model kind, red where the model hierarchy makes it invalid."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .column_layout import Column

if TYPE_CHECKING:
    import bpy

    from ...prim_tree import RowDetails


def _draw_cell(layout: bpy.types.UILayout, details: RowDetails) -> None:
    layout.alert = details.is_invalid_model
    layout.label(text=details.model_kind)


KIND_COLUMN = Column("Kind", "show_kind_column", _draw_cell, "kind_column_units")
