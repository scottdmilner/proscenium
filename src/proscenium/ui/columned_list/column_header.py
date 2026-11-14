"""A list's header row above it, with each column's title over its cells, and telling whether the list scrolls.

A header is a row drawn above the list and split as its rows are; the list's own padding offsets its columns by a few
pixels. A scrolling list's rows are narrower by its scrollbar, so the header leaves the scrollbar's width blank and
splits the rest as they split theirs. Python can't read whether a list scrolls, but a list draws only the rows on
screen, so fewer drawn than it holds means it does: its `draw_item` counts each (`count_drawn_row`), and the header,
drawn into a layout made before the list and filled after it, reads the count.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import column_layout

if TYPE_CHECKING:
    import bpy

# What a scrolling list's scrollbar takes from its rows' width, the gap before it included.
SCROLLBAR_UNITS = 0.5


class _ColumnHeaderState:
    """Each list's rows drawn in its current draw, by its UIList's idname and its list ID."""

    drawn_row_counts: dict[tuple[str, str], int] = {}


def start_counting_rows(list_idname: str, list_id: str) -> None:
    """Start counting a list's drawn rows, before its template_list."""
    _ColumnHeaderState.drawn_row_counts[list_idname, list_id] = 0


def count_drawn_row(list_idname: str, list_id: str) -> None:
    """Count a row the list drew, from its draw_item."""
    key = (list_idname, list_id)
    _ColumnHeaderState.drawn_row_counts[key] = _ColumnHeaderState.drawn_row_counts.get(key, 0) + 1


def is_list_scrolling(list_idname: str, list_id: str, row_count: int) -> bool:
    """Whether a list drew fewer of its row_count rows than it holds, and so scrolls; it ends the count."""
    return _ColumnHeaderState.drawn_row_counts.pop((list_idname, list_id), 0) < row_count


def header_row(layout: bpy.types.UILayout, context: bpy.types.Context, is_scrolling: bool) -> bpy.types.UILayout:
    """The layout a header's columns split, leaving a scrolling list's scrollbar width blank after it."""
    if not is_scrolling:
        return layout
    scrollbar_split = layout.split(factor=column_layout.split_factor_leaving(context, SCROLLBAR_UNITS, 0.0))
    row = scrollbar_split.row()
    scrollbar_split.label(text="")
    return row


def draw_column_titles(
    layout: bpy.types.UILayout, widths_units: list[float], shown: list[column_layout.Column[Any]]
) -> None:
    """Each shown column's title, or its icon, over its cells, splitting layout as the rows split theirs."""
    for cell, column in zip(column_layout.column_cells(layout, widths_units, shown), shown, strict=True):
        if column.header_icon:
            cell.label(text="", icon=column.header_icon)
        else:
            cell.label(text=column.title)
