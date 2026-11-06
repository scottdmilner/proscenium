"""Custom badge icons, drawn into a preview collection from pixels made here, so they need no image files.

A layout takes them by number (`icon_value=icon_id(...)`), not by Blender's icon names. They keep the colors they're
drawn in; Blender's own icons are recolored by the theme, these aren't.
"""

from __future__ import annotations

from typing import Any

import bpy.utils.previews

SIZE = 32  # pixels; Blender scales a preview to the row's icon size

# Badge name -> (RGBA color, shape). One per composition fact a row marks.
BADGES: dict[str, tuple[tuple[float, float, float, float], str]] = {
    "payload": ((0.95, 0.55, 0.15, 1.0), "circle"),
    "variants": ((0.35, 0.80, 0.40, 1.0), "diamond"),
    "instance": ((0.70, 0.45, 0.95, 1.0), "ring"),
    "references": ((0.35, 0.60, 0.95, 1.0), "square"),
}


class _Icons:
    previews: Any = None  # the ImagePreviewCollection, while registered


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
    for row in range(SIZE):
        for column in range(SIZE):
            x = (column + 0.5) / SIZE * 2 - 1
            y = (row + 0.5) / SIZE * 2 - 1
            pixels.extend(color if _inside(shape, x, y) else (0.0, 0.0, 0.0, 0.0))
    return pixels


def register() -> None:
    """Make the preview collection and draw every badge into it."""
    previews: Any = bpy.utils.previews.new()
    for name, (color, shape) in BADGES.items():
        preview = previews.new(name)
        preview.icon_size = (SIZE, SIZE)
        preview.icon_pixels_float = _pixels(color, shape)
    _Icons.previews = previews


def unregister() -> None:
    """Free the preview collection."""
    if _Icons.previews is not None:
        bpy.utils.previews.remove(_Icons.previews)
        _Icons.previews = None


def icon_id(name: str) -> int:
    """The number a layout's `icon_value` takes for a badge."""
    return _Icons.previews[name].icon_id
