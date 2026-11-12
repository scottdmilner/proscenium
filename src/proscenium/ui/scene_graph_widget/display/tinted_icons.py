"""Icons in any color, as preview icons drawn from masks: Blender's own icons, and the dashed tree guide line.

Blender draws its icons only in the theme's icon color, so an icon in another color is drawn from a mask of its SVG:
how much of each pixel the icon covers (`blender_icons/`, which `tools/row_icon_masks.py` makes for every icon a row
can show). The dashed guide line's mask is made here. A layout takes an icon in a color by number
(`icon_value=icon_id(...)`); its preview is drawn the first time that icon is asked for in that color, and kept until
the collection is removed. In background mode, previews get number 0.

A label draws its icon 16 points tall in a 20-point row, whatever the icon's pixels, so a line drawn into an icon
can't reach its row's edges. The guide line is dashed, and the dashes are timed so the gap a row leaves at its edges is
one of the gaps between them: down a column of rows, the dashes run evenly.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import bpy
import bpy.utils.previews
import numpy as np

from . import widget_colors

MASKS_PATH = Path(__file__).parent / "blender_icons" / "row_icon_masks.npz"
DASHED_LINE_SIZE_PIXELS = 32
# The line's pixel columns, left of the icon's center: a label in a guide level draws its icon from the level's left,
# so these put the line where the level's own line is, under the center of the parent's chevron.
DASHED_LINE_COLUMNS = (8, 9)
# The rows left blank, bottom first: dashes of a quarter of the row's 20 points, and gaps as long, two to an icon,
# with the 2 points the icon leaves at each edge of its row making up the gap there.
DASHED_LINE_GAP_ROWS = (*range(2), *range(12, 22))


class _TintedIconsState:
    """The preview collection, while registered."""

    previews: Any = None


@functools.cache
def _masks() -> dict[str, np.ndarray]:
    """Each icon's mask, by Blender's icon name: how much of each pixel it covers, 0 to 255, bottom row first."""
    with np.load(MASKS_PATH) as masks:
        return {name: masks[name] for name in masks.files}


@functools.cache
def _dashed_line_mask() -> np.ndarray:
    """The dashed guide line's mask, as Blender's icons' are."""
    coverages = np.zeros((DASHED_LINE_SIZE_PIXELS, DASHED_LINE_SIZE_PIXELS), dtype=np.uint8)
    coverages[:, list(DASHED_LINE_COLUMNS)] = 255
    coverages[list(DASHED_LINE_GAP_ROWS), :] = 0
    return coverages


def create_icons() -> None:
    """Create the preview collection the icons are drawn into as they're asked for."""
    _TintedIconsState.previews = bpy.utils.previews.new()


def remove_icons() -> None:
    """Free the preview collection, and every icon drawn into it."""
    if _TintedIconsState.previews is not None:
        bpy.utils.previews.remove(_TintedIconsState.previews)
        _TintedIconsState.previews = None


def icon_names() -> list[str]:
    """Every one of Blender's icons there's a mask for, by its icon name."""
    return sorted(_masks())


def _mask_icon_id(name: str, coverages: np.ndarray, color: widget_colors.RGB) -> int:
    """The number of a mask's icon in a color, its preview named for both and drawn the first time it's asked for."""
    rounded = widget_colors.rounded_color(color)
    preview_name = f"{name}_{widget_colors.color_name(rounded)}"
    previews = _TintedIconsState.previews
    preview = previews.get(preview_name)
    if preview is None:
        preview = previews.new(preview_name)
        preview.icon_size = coverages.shape[::-1]
        preview.icon_pixels_float = widget_colors.colored_pixels(coverages, rounded)
    return preview.icon_id


def icon_id(icon: str, color: widget_colors.RGB) -> int | None:
    """The number a layout's `icon_value` takes for one of Blender's icons in an RGB color, or None without a mask."""
    coverages = _masks().get(icon)
    return None if coverages is None else _mask_icon_id(icon, coverages, color)


def dashed_line_icon_id(color: widget_colors.RGB) -> int:
    """The number a layout's `icon_value` takes for a dashed guide line in an RGB color."""
    return _mask_icon_id("dashed", _dashed_line_mask(), color)  # lowercase, so no Blender icon's name
