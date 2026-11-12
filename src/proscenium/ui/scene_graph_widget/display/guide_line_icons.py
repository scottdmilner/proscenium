"""Dashed tree guide lines in any color, as preview icons a guide level's label draws.

A label draws its icon 16 points tall in a 20-point row, whatever the icon's pixels, so a line drawn into an icon
can't reach its row's edges. The line is dashed, and the dashes are timed so the gap a row leaves at its edges is one
of the gaps between them: down a column of rows, the dashes run evenly. A layout takes a line in a color by number
(`icon_value=icon_id(...)`); its preview is drawn the first time it's asked for in that color.
"""

from __future__ import annotations

from typing import Any

import bpy
import bpy.utils.previews
import numpy as np

from . import tinted_icons

ICON_SIZE_PIXELS = 32
# The line's pixel columns, left of the icon's center: a label in a guide level draws its icon from the level's left,
# so these put the line where the level's own line is, under the center of the parent's chevron.
LINE_COLUMNS = (8, 9)
# The rows left blank, bottom first: dashes of a quarter of the row's 20 points, and gaps as long, two to an icon,
# with the 2 points the icon leaves at each edge of its row making up the gap there.
GAP_ROWS = (*range(2), *range(12, 22))


class _GuideLineIconsState:
    """The preview collection, while registered."""

    previews: Any = None


def _dashed_line_coverages() -> np.ndarray:
    coverages = np.zeros((ICON_SIZE_PIXELS, ICON_SIZE_PIXELS), dtype=np.uint8)
    coverages[:, list(LINE_COLUMNS)] = 255
    coverages[list(GAP_ROWS), :] = 0
    return coverages


def create_icons() -> None:
    """Create the preview collection the lines are drawn into as they're asked for."""
    _GuideLineIconsState.previews = bpy.utils.previews.new()


def remove_icons() -> None:
    """Free the preview collection, and every line drawn into it."""
    if _GuideLineIconsState.previews is not None:
        bpy.utils.previews.remove(_GuideLineIconsState.previews)
        _GuideLineIconsState.previews = None


def dashed_line_icon_id(color: tuple[float, float, float]) -> int:
    """The number a layout's `icon_value` takes for a dashed guide line in an RGB color."""
    rounded = tinted_icons.rounded_color(color)
    name = f"dashed_{'_'.join(str(channel) for channel in rounded)}"
    previews = _GuideLineIconsState.previews
    preview = previews.get(name)
    if preview is None:
        preview = previews.new(name)
        preview.icon_size = (ICON_SIZE_PIXELS, ICON_SIZE_PIXELS)
        preview.icon_pixels_float = tinted_icons.colored_pixels(_dashed_line_coverages(), rounded)
    return preview.icon_id
