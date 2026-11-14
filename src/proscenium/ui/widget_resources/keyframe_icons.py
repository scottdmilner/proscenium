"""Keyframe icons for list rows: a diamond in Blender's colors for an animated property, outlined as its keyframes are.

Blender colors an animated property's field one way when it has a key on the current frame and another when it's
animated but not keyed there (the theme's State widget colors, `inner_key` and `inner_anim`), and draws a keyframe as
a diamond with a dark border (the Dope Sheet's `keyframe_border`). A keyframe icon is that diamond, filled in either
color (`KeyframeFill`). Its two icons are drawn into a preview collection the first time each is asked for, and drawn
again when the theme's colors change (`redraw_icons_if_theme_changed`), as the badges are; the colors are read in
`theme_colors`. In background mode, previews get number 0.
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Any

import bpy
import bpy.utils.previews

from . import theme_colors

if TYPE_CHECKING:
    from .theme_colors import ThemeColors

ICON_SIZE_PIXELS = 32  # Blender scales a preview to the row's icon size
# The diamond's half width and half height, and its border's width, in the icon's coordinates, which run from -1 to 1:
# a square turned 45 degrees, as Blender draws a keyframe, about as tall as a row's text.
DIAMOND_HALF_WIDTH = 0.72
DIAMOND_HALF_HEIGHT = DIAMOND_HALF_WIDTH
BORDER_WIDTH = 0.16


class KeyframeFill(enum.Enum):
    """Which of Blender's animated-property colors a keyframe icon's diamond is filled in."""

    KEYED = "keyed"  # a key on the current time code
    ANIMATED = "animated"  # animated, but no key here


class _KeyframeIconsState:
    """The preview collection, while registered, the fills drawn into it, and the theme colors they were drawn in."""

    previews: Any = None
    drawn_fills: set[KeyframeFill] = set()
    drawn_theme_colors: ThemeColors | None = None


def _diamond_distance(x: float, y: float) -> float:
    """How far a point is outside the diamond (negative inside), across its edge."""
    width, height = DIAMOND_HALF_WIDTH, DIAMOND_HALF_HEIGHT
    return (abs(x) * height + abs(y) * width - width * height) / (width * width + height * height) ** 0.5


def _coverage(distance: float, pixel_width: float) -> float:
    """How much of a pixel a shape covers, from the distance outside it of the pixel's center."""
    return max(0.0, min(1.0, 0.5 - distance / pixel_width))


def _pixels(fill_color: theme_colors.RGB, border_color: theme_colors.RGBA) -> list[float]:
    """The icon's pixels: the diamond filled in a color inside its border, premultiplied, as previews take them."""
    pixel_width = 2 / ICON_SIZE_PIXELS
    pixels: list[float] = []
    for row in range(ICON_SIZE_PIXELS):
        for column in range(ICON_SIZE_PIXELS):
            x = (column + 0.5) * pixel_width - 1
            y = (row + 0.5) * pixel_width - 1
            distance = _diamond_distance(x, y)
            outer = _coverage(distance, pixel_width)  # the diamond with its border
            inner = _coverage(distance + BORDER_WIDTH, pixel_width)  # the fill inside the border
            border = (outer - inner) * border_color[3]
            pixels.extend((*(fill_color[i] * inner + border_color[i] * border for i in range(3)), inner + border))
    return pixels


def _fill_color(fill: KeyframeFill, colors: ThemeColors) -> theme_colors.RGB:
    return colors.keyed_color if fill is KeyframeFill.KEYED else colors.animated_color


def _draw_icon(preview: Any, fill: KeyframeFill, colors: ThemeColors) -> None:
    preview.icon_pixels_float = _pixels(_fill_color(fill, colors), colors.keyframe_border_color)


def create_icons() -> None:
    """Create the preview collection the keyframe icons are drawn into as they're asked for."""
    _KeyframeIconsState.previews = bpy.utils.previews.new()
    _KeyframeIconsState.drawn_fills = set()
    _KeyframeIconsState.drawn_theme_colors = theme_colors.read_theme_colors()


def redraw_icons_if_theme_changed() -> None:
    """Draw the icons again if the theme's colors, as last read, changed since they were drawn."""
    if _KeyframeIconsState.previews is None:
        return
    colors = theme_colors.last_read_theme_colors()
    if colors == _KeyframeIconsState.drawn_theme_colors:
        return
    for fill in _KeyframeIconsState.drawn_fills:
        _draw_icon(_KeyframeIconsState.previews[fill.value], fill, colors)
    _KeyframeIconsState.drawn_theme_colors = colors


def remove_icons() -> None:
    """Free the preview collection."""
    if _KeyframeIconsState.previews is not None:
        bpy.utils.previews.remove(_KeyframeIconsState.previews)
        _KeyframeIconsState.previews = None
    _KeyframeIconsState.drawn_fills = set()
    _KeyframeIconsState.drawn_theme_colors = None


def icon_id(fill: KeyframeFill) -> int:
    """The number a layout's `icon_value` takes for a keyframe icon, drawn the first time it's asked for."""
    previews = _KeyframeIconsState.previews
    preview = previews.get(fill.value)
    if preview is None:
        preview = previews.new(fill.value)
        preview.icon_size = (ICON_SIZE_PIXELS, ICON_SIZE_PIXELS)
        colors = _KeyframeIconsState.drawn_theme_colors or theme_colors.last_read_theme_colors()
        _draw_icon(preview, fill, colors)
        _KeyframeIconsState.drawn_fills.add(fill)
    return preview.icon_id
