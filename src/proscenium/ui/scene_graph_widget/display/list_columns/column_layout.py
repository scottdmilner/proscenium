"""What the columns share: `Column`, a column after the name, and the widths that lay the columns out in a row."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Callable

    import bpy
    from bpy.stub_internal.rna_enums import IconItems

    from ...prim_tree import RowDetails
    from ..widget_properties import SceneGraphViewProperties

CellAlignment = Literal["EXPAND", "LEFT", "CENTER", "RIGHT"]  # a layout's alignment
REGION_MARGIN_UNITS = 2.0  # what a region's width leaves out of a list row's: the panel's margins and the list's


class Column(NamedTuple):
    """A column after the name: its title, the view properties that show it and set its width, and its cells."""

    title: str
    show_property: str
    draw_cell: Callable[[bpy.types.UILayout, RowDetails], None]  # draws a row's cell from the row's details
    units_property: str = ""  # its width's property, or empty for a column of fixed_units
    fixed_units: float = 0.0  # the width of a column the settings can't resize
    header_icon: IconItems | None = None  # in place of the title in the header, for a column too narrow for it
    alignment: CellAlignment = "LEFT"  # its cells', in the header and the rows: RIGHT for numbers


def column_units(properties: SceneGraphViewProperties, column: Column) -> float:
    """A column's width in UI units: its setting's, or its fixed width."""
    return getattr(properties, column.units_property) if column.units_property else column.fixed_units


def unit_pixels(context: bpy.types.Context) -> float:
    """Blender's widget unit in pixels: 18 at a scale of 1, and a pixel's line on each side."""
    preferences = context.preferences
    if preferences is None:  # none to read the scale from: a scale of 1
        return 18 + 2
    system = preferences.system
    return round(18 * system.ui_scale) + 2 * system.pixel_size


def split_factor_leaving(context: bpy.types.Context | None, right_units: float, least_factor: float) -> float:
    """A split's factor that leaves its right side right_units wide, or least_factor where the region is too narrow.

    A split takes a share of its width, not a width, so the share is worked out from the region's.
    """
    width_units = row_units(context)
    if width_units is None or right_units == 0:
        return least_factor
    return max(least_factor, 1 - right_units / width_units)


def row_units(context: bpy.types.Context | None) -> float | None:
    """A list row's width in UI units: the region's, less its margins; None without a region wider than them."""
    region = context.region if context is not None else None
    if context is None or region is None:
        return None
    width_units = region.width / unit_pixels(context) - REGION_MARGIN_UNITS
    return width_units if width_units > 0 else None


def column_cells(
    layout: bpy.types.UILayout, properties: SceneGraphViewProperties, shown: list[Column]
) -> list[bpy.types.UILayout]:
    """One cell per shown column, aligned as it says, sharing a layout's width in proportion to the columns' widths."""
    cells = []
    remaining_units = sum(column_units(properties, column) for column in shown)
    for column in shown[:-1]:
        units = column_units(properties, column)
        split = layout.split(factor=units / remaining_units, align=True)  # this column, then the rest
        cells.append(split.row(align=True))
        layout = split.row(align=True)
        remaining_units -= units
    if shown:
        cells.append(layout.row(align=True))
    for cell, column in zip(cells, shown, strict=True):
        cell.alignment = column.alignment
    return cells


def fixed_width(layout: bpy.types.UILayout, width_units: float) -> bpy.types.UILayout:
    """A row in layout of a fixed width in UI units."""
    cell = layout.row(align=True)
    cell.ui_units_x = width_units
    return cell
