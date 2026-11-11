"""Badge icons for scene graph rows, drawn into a preview collection from pixels made here, so they need no files.

A layout takes them by number (`icon_value=icon_id(...)`), not by Blender's icon names. They keep the colors they're
drawn in; Blender's own icons are recolored by the theme, these aren't. In background mode, previews get number 0.
"""

from __future__ import annotations

from typing import Any

import bpy.utils.previews

from ..prim_tree.prim_descriptions import Badge

ICON_SIZE_PIXELS = 32  # Blender scales a preview to the row's icon size

# Each badge's RGBA color and shape.
BADGE_LOOKS: dict[Badge, tuple[tuple[float, float, float, float], str]] = {
    Badge.PAYLOAD: ((0.95, 0.55, 0.15, 1.0), "circle"),
    Badge.VARIANTS: ((0.35, 0.80, 0.40, 1.0), "diamond"),
    Badge.INSTANCE: ((0.70, 0.45, 0.95, 1.0), "ring"),
    Badge.REFERENCES: ((0.35, 0.60, 0.95, 1.0), "square"),
}


class _BadgeIconsState:
    """The preview collection, while registered."""

    previews: Any = None


def _inside(shape: str, x: float, y: float) -> bool:
    # x and y run from -1 to 1 across the icon.
    radius = (x * x + y * y) ** 0.5
    if shape == "circle":
        return radius < 0.7
    if shape == "ring":
        return 0.42 < radius < 0.72
    if shape == "diamond":
        return abs(x) + abs(y) < 0.8
    return max(abs(x), abs(y)) < 0.58  # square


def _pixels(color: tuple[float, float, float, float], shape: str) -> list[float]:
    pixels: list[float] = []
    for row in range(ICON_SIZE_PIXELS):
        for column in range(ICON_SIZE_PIXELS):
            x = (column + 0.5) / ICON_SIZE_PIXELS * 2 - 1
            y = (row + 0.5) / ICON_SIZE_PIXELS * 2 - 1
            pixels.extend(color if _inside(shape, x, y) else (0.0, 0.0, 0.0, 0.0))
    return pixels


def create_icons() -> None:
    """Create the preview collection and draw every badge into it."""
    previews: Any = bpy.utils.previews.new()
    for badge, (color, shape) in BADGE_LOOKS.items():
        preview = previews.new(badge.value)
        preview.icon_size = (ICON_SIZE_PIXELS, ICON_SIZE_PIXELS)
        preview.icon_pixels_float = _pixels(color, shape)
    _BadgeIconsState.previews = previews


def remove_icons() -> None:
    """Free the preview collection."""
    if _BadgeIconsState.previews is not None:
        bpy.utils.previews.remove(_BadgeIconsState.previews)
        _BadgeIconsState.previews = None


def icon_id(badge: Badge) -> int:
    """The number a layout's `icon_value` takes for a badge."""
    return _BadgeIconsState.previews[badge.value].icon_id
