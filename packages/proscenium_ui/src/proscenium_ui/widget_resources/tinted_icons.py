"""Icons in any color, as preview icons drawn from masks: Blender's own icons, and masks a widget makes itself.

Blender draws its icons only in the theme's icon color, so an icon in another color is drawn from a mask of its SVG:
how much of each pixel the icon covers (`blender_icons/`, which `tools/row_icon_masks.py` makes for every icon a
widget's rows can show). A widget may draw a mask of its own the same way (`mask_icon_id`). A layout takes an icon in a
color by number (`icon_value=icon_id(...)`); its preview is drawn the first time that icon is asked for in that color,
and kept until the collection is removed. In background mode, previews get number 0.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import bpy
import bpy.utils.previews
import numpy as np

from . import theme_colors

MASKS_PATH = Path(__file__).parent / "blender_icons" / "row_icon_masks.npz"


class _TintedIconsState:
    """The preview collection, while registered."""

    previews: Any = None


@functools.cache
def _masks() -> dict[str, np.ndarray]:
    """Each icon's mask, by Blender's icon name: how much of each pixel it covers, 0 to 255, bottom row first."""
    with np.load(MASKS_PATH) as masks:
        return {name: masks[name] for name in masks.files}


def create_icons() -> None:
    """Create the preview collection the icons are drawn into as they're asked for."""
    _TintedIconsState.previews = bpy.utils.previews.new()


def remove_icons() -> None:
    """Free the preview collection, and every icon drawn into it."""
    if _TintedIconsState.previews is not None:
        bpy.utils.previews.remove(_TintedIconsState.previews)
        _TintedIconsState.previews = None


def mask_icon_id(name: str, coverages: np.ndarray, color: theme_colors.RGB) -> int:
    """The number a layout's `icon_value` takes for a mask's icon in a color, drawn the first time it's asked for.

    A widget's own mask is named in lowercase, so no Blender icon's name, and holds coverages as `blender_icons/`
    does: 0 to 255, bottom row first.
    """
    rounded = theme_colors.rounded_color(color)
    preview_name = f"{name}_{theme_colors.color_name(rounded)}"
    previews = _TintedIconsState.previews
    preview = previews.get(preview_name)
    if preview is None:
        preview = previews.new(preview_name)
        preview.icon_size = coverages.shape[::-1]
        preview.icon_pixels_float = theme_colors.colored_pixels(coverages, rounded)
    return preview.icon_id


def icon_id(icon: str, color: theme_colors.RGB) -> int | None:
    """The number a layout's `icon_value` takes for one of Blender's icons in an RGB color, or None without a mask."""
    coverages = _masks().get(icon)
    return None if coverages is None else mask_icon_id(icon, coverages, color)
