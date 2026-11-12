"""Blender's own icons in any color, as preview icons drawn from masks of Blender's icon SVGs.

Blender draws its icons only in the theme's icon color, so an icon in another color is drawn from a mask of its SVG:
how much of each pixel the icon covers (`blender_icons/`, which `tools/row_icon_masks.py` makes for every icon a row
can show). A layout takes an icon in a color by number (`icon_value=icon_id(...)`); its preview is drawn the first
time that icon is asked for in that color, and kept until the collection is removed. In background mode, previews get
number 0.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import bpy
import bpy.utils.previews
import numpy as np

MASKS_PATH = Path(__file__).parent / "blender_icons" / "row_icon_masks.npz"
COLOR_DIGITS = 4  # a color's channels are rounded to this many digits to name its previews


class _TintedIconsState:
    """The preview collection, while registered."""

    previews: Any = None


@functools.cache
def _masks() -> dict[str, np.ndarray]:
    """Each icon's mask, by Blender's icon name: how much of each pixel it covers, 0 to 255, bottom row first."""
    with np.load(MASKS_PATH) as masks:
        return {name: masks[name] for name in masks.files}


def rounded_color(color: tuple[float, float, float]) -> tuple[float, float, float]:
    """A color with its channels rounded to COLOR_DIGITS, as it names its previews."""
    red, green, blue = color
    return round(red, COLOR_DIGITS), round(green, COLOR_DIGITS), round(blue, COLOR_DIGITS)


def colored_pixels(coverages: np.ndarray, color: tuple[float, float, float]) -> list[float]:
    """Pixels of an RGB color, each as opaque as its coverage of 0 to 255, premultiplied, as previews take them."""
    alphas = coverages.astype(np.float32).ravel() / 255
    return np.column_stack([alphas * channel for channel in color] + [alphas]).ravel().tolist()


def create_icons() -> None:
    """Create the preview collection the icons are drawn into as they're asked for."""
    _TintedIconsState.previews = bpy.utils.previews.new()


def remove_icons() -> None:
    """Free the preview collection, and every icon drawn into it."""
    if _TintedIconsState.previews is not None:
        bpy.utils.previews.remove(_TintedIconsState.previews)
        _TintedIconsState.previews = None


def icon_names() -> list[str]:
    """Every icon there's a mask for, by Blender's icon name."""
    return sorted(_masks())


def icon_id(icon: str, color: tuple[float, float, float]) -> int | None:
    """The number a layout's `icon_value` takes for one of Blender's icons in an RGB color, or None without a mask."""
    coverages = _masks().get(icon)
    if coverages is None:
        return None
    rounded = rounded_color(color)
    name = f"{icon}_{'_'.join(str(channel) for channel in rounded)}"
    previews = _TintedIconsState.previews
    preview = previews.get(name)
    if preview is None:
        preview = previews.new(name)
        preview.icon_size = coverages.shape[::-1]
        preview.icon_pixels_float = colored_pixels(coverages, rounded)
    return preview.icon_id
