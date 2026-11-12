"""Badge icons for scene graph rows, drawn into a preview collection from pixels made here, so they need no files.

Each badge is its arc's LIVRPS letter, in bold strokes, on its piece of a dark rounded block: a row's badges are
labels side by side, so the block is drawn into their icons, each badge drawing the piece for its place in the row
(`BadgePlace`). The colors are the theme's: each letter takes one of its collection colors, and the block its pie
menu's color and roundness, the dark of a PIE_MENU button. A badge whose arc isn't in effect, an unloaded payload or
variant sets with nothing selected, is greyed out: its letter is the pie menu's text color, half blended into the
block. Preview icons keep the colors they're drawn in, so the
icons are drawn again when the theme's colors change (`redraw_icons_if_theme_changed`). A layout takes the icons by
number (`icon_value=icon_id(...)`), not by Blender's icon names. In background mode, previews get number 0.
"""

from __future__ import annotations

import enum
import functools
import math
from dataclasses import dataclass
from typing import Any

import bpy
import bpy.utils.previews

from ..prim_tree.prim_descriptions import Badge

ICON_SIZE_PIXELS = 32  # Blender scales a preview to the row's icon size
STROKE_HALF_WIDTH = 0.19  # in the letters' coordinates below: bold
LETTER_SCALE = 0.8  # the letters' size in the icon, so they stand about as tall as a row's text

# A letter's strokes: a segment from one point to another, or an arc of a circle (center, radius, and the angles in
# degrees it runs between, counterclockwise from the first). The letters fill x from -0.5 to 0.5 and y from -0.75
# to 0.75, y up, in an icon running from -1 to 1 across before LETTER_SCALE.
Point = tuple[float, float]
Segment = tuple[Point, Point]
Arc = tuple[Point, float, float, float]
_P_BOWL: tuple[Segment | Arc, ...] = (
    ((-0.42, -0.75), (-0.42, 0.75)),
    ((-0.42, 0.75), (0.05, 0.75)),
    ((-0.42, -0.05), (0.05, -0.05)),
    ((0.05, 0.35), 0.4, -90.0, 90.0),
)
_S_MIDDLE = 0.06  # where the S's two arcs meet, a little above center, so its lower one is the wider
LETTER_STROKES: dict[str, tuple[Segment | Arc, ...]] = {
    "I": (((0.0, -0.75), (0.0, 0.75)), ((-0.3, 0.75), (0.3, 0.75)), ((-0.3, -0.75), (0.3, -0.75))),
    "V": (((-0.57, 0.75), (0.0, -0.75)), ((0.0, -0.75), (0.57, 0.75))),  # wider than the others, as a V is
    "R": (*_P_BOWL, ((0.0, -0.05), (0.45, -0.75))),
    "P": _P_BOWL,
    "S": (
        ((0.0, (0.75 + _S_MIDDLE) / 2), (0.75 - _S_MIDDLE) / 2, 20.0, 270.0),
        ((0.0, (_S_MIDDLE - 0.75) / 2), (0.75 + _S_MIDDLE) / 2, -160.0, 90.0),
    ),
}

GREYED_LETTER_WEIGHT = 0.5  # how much of a greyed-out letter's color is the pie menu's text color, the rest the block's
# Each badge's color, as an index into the theme's eight collection colors (COLLECTION_COLOR_01 is index 0: red,
# orange, yellow, green, blue, violet, pink, brown), and its letter.
BADGE_LOOKS: dict[Badge, tuple[int, str]] = {
    Badge.INHERITS: (5, "I"),  # violet
    Badge.VARIANTS: (3, "V"),  # green
    Badge.REFERENCES: (4, "R"),  # blue
    Badge.PAYLOAD: (1, "P"),  # orange
    Badge.SPECIALIZES: (2, "S"),  # yellow
}


@dataclass(frozen=True, slots=True)
class BadgeThemeColors:
    """The theme's colors the badges are drawn in, compared to tell when the icons need drawing again."""

    block_color: tuple[float, ...]  # RGBA, the pie menu's inner color
    block_roundness: float  # the pie menu's: 1 rounds an end into a half circle
    text_color: tuple[float, ...]  # RGB, the pie menu's text color, which a greyed-out letter is drawn in
    collection_colors: tuple[tuple[float, ...], ...]  # RGB, the eight collection colors in order


# Without preferences to read the theme from: the default theme's colors.
DEFAULT_THEME_COLORS = BadgeThemeColors(
    block_color=(0.094, 0.094, 0.094, 1.0),
    block_roundness=0.4,
    text_color=(0.851, 0.851, 0.851),
    collection_colors=(
        (0.886, 0.376, 0.357),
        (0.945, 0.639, 0.333),
        (0.945, 0.863, 0.333),
        (0.482, 0.8, 0.482),
        (0.365, 0.714, 0.918),
        (0.553, 0.349, 0.855),
        (0.776, 0.451, 0.722),
        (0.478, 0.329, 0.255),
    ),
)


class BadgePlace(enum.Enum):
    """Where a badge sits among its row's badges, which sets which ends of its piece of the block are rounded."""

    ALONE = (True, True)
    FIRST = (True, False)
    MIDDLE = (False, False)
    LAST = (False, True)

    @classmethod
    def at(cls, badge_index: int, badge_count: int) -> BadgePlace:
        """The place of a row's badge, by its index among the row's badge_count badges."""
        if badge_count == 1:
            return cls.ALONE
        if badge_index == 0:
            return cls.FIRST
        return cls.LAST if badge_index == badge_count - 1 else cls.MIDDLE


class _BadgeIconsState:
    """The preview collection, while registered, and the theme colors its icons were last drawn in."""

    previews: Any = None
    drawn_theme_colors: BadgeThemeColors | None = None


def _segment_distance(x: float, y: float, segment: Segment) -> float:
    (x0, y0), (x1, y1) = segment
    dx, dy = x1 - x0, y1 - y0
    along = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - x0 - along * dx, y - y0 - along * dy)


def _arc_distance(x: float, y: float, arc: Arc) -> float:
    (cx, cy), radius, start_degrees, end_degrees = arc
    angle = math.degrees(math.atan2(y - cy, x - cx))
    if (angle - start_degrees) % 360 <= (end_degrees - start_degrees) % 360:
        return abs(math.hypot(x - cx, y - cy) - radius)
    ends = [math.radians(start_degrees), math.radians(end_degrees)]
    return min(math.hypot(x - cx - radius * math.cos(end), y - cy - radius * math.sin(end)) for end in ends)


def _stroke_distance(x: float, y: float, stroke: Segment | Arc) -> float:
    if len(stroke) == 2:
        return _segment_distance(x, y, stroke)
    return _arc_distance(x, y, stroke)


def _letter_distance(letter: str, x: float, y: float) -> float:
    """How far a point is from the nearest of a letter's strokes' center lines."""
    return min(_stroke_distance(x, y, stroke) for stroke in LETTER_STROKES[letter])


def _block_distance(x: float, y: float, place: BadgePlace, corner_radius: float) -> float:
    """How far a point is outside the block's piece (negative inside), in the icon's coordinates.

    The piece fills the icon, its rounded ends at the icon's edges; an end that isn't rounded runs past the edge, so
    it meets the next badge's piece square.
    """
    rounds_left, rounds_right = place.value
    left, right = (-1.0 if rounds_left else -3.0), (1.0 if rounds_right else 3.0)
    half_width, half_height = (right - left) / 2, 1.0
    qx = abs(x - (left + right) / 2) - (half_width - corner_radius)
    qy = abs(y) - (half_height - corner_radius)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - corner_radius


def _coverage(distance: float, pixel_width: float) -> float:
    """How much of a pixel a shape covers, from the distance outside it of the pixel's center."""
    return max(0.0, min(1.0, 0.5 - distance / pixel_width))


@functools.cache
def _coverages(letter: str, place: BadgePlace, block_roundness: float) -> tuple[tuple[float, float], ...]:
    """How much of each pixel a badge's letter and its piece of the block cover, bottom row first.

    Kept, so drawing the icons again in new colors needn't work out their shapes again.
    """
    pixel_width = 2 / ICON_SIZE_PIXELS
    coverages: list[tuple[float, float]] = []
    for row in range(ICON_SIZE_PIXELS):
        for column in range(ICON_SIZE_PIXELS):
            x = (column + 0.5) * pixel_width - 1
            y = (row + 0.5) * pixel_width - 1
            letter_distance = _letter_distance(letter, x / LETTER_SCALE, y / LETTER_SCALE) * LETTER_SCALE
            letter_coverage = _coverage(letter_distance - STROKE_HALF_WIDTH * LETTER_SCALE, pixel_width)
            block_coverage = _coverage(_block_distance(x, y, place, block_roundness), pixel_width)
            coverages.append((letter_coverage, block_coverage))
    return tuple(coverages)


def _pixels(
    coverages: tuple[tuple[float, float], ...], letter_color: tuple[float, ...], block_color: tuple[float, ...]
) -> list[float]:
    """A badge's pixels: its letter over its piece of the block, premultiplied, as previews take them."""
    pixels: list[float] = []
    for letter_alpha, block_coverage in coverages:
        under = block_coverage * block_color[3] * (1 - letter_alpha)  # the block where the letter doesn't cover it
        pixels.extend(
            (*(letter_color[i] * letter_alpha + block_color[i] * under for i in range(3)), letter_alpha + under)
        )
    return pixels


def _read_theme_colors() -> BadgeThemeColors:
    preferences = bpy.context.preferences
    if preferences is None:  # the context has none to read
        return DEFAULT_THEME_COLORS
    theme = preferences.themes[0]
    pie_menu = theme.user_interface.wcol_pie_menu
    return BadgeThemeColors(
        block_color=tuple(pie_menu.inner),
        block_roundness=pie_menu.roundness,
        text_color=(pie_menu.text.r, pie_menu.text.g, pie_menu.text.b),
        collection_colors=tuple((item.color.r, item.color.g, item.color.b) for item in theme.collection_color),
    )


def _draw_icons(theme_colors: BadgeThemeColors) -> None:
    block_color = theme_colors.block_color
    greyed_color = tuple(
        GREYED_LETTER_WEIGHT * text + (1 - GREYED_LETTER_WEIGHT) * block
        for text, block in zip(theme_colors.text_color, block_color, strict=False)
    )
    for badge, (collection_color_index, letter) in BADGE_LOOKS.items():
        for is_greyed in (False, True):
            letter_color = greyed_color if is_greyed else theme_colors.collection_colors[collection_color_index]
            for place in BadgePlace:
                coverages = _coverages(letter, place, theme_colors.block_roundness)
                preview = _BadgeIconsState.previews[_preview_name(badge, place, is_greyed)]
                preview.icon_pixels_float = _pixels(coverages, letter_color, block_color)
    _BadgeIconsState.drawn_theme_colors = theme_colors


def _preview_name(badge: Badge, place: BadgePlace, is_greyed: bool) -> str:
    return f"{badge.value}_{place.name}{'_greyed' if is_greyed else ''}"


def create_icons() -> None:
    """Create the preview collection and draw every badge, in every place, into it, in the theme's colors."""
    previews: Any = bpy.utils.previews.new()
    for badge in BADGE_LOOKS:
        for place in BadgePlace:
            for is_greyed in (False, True):
                preview = previews.new(_preview_name(badge, place, is_greyed))
                preview.icon_size = (ICON_SIZE_PIXELS, ICON_SIZE_PIXELS)
    _BadgeIconsState.previews = previews
    _draw_icons(_read_theme_colors())


def redraw_icons_if_theme_changed() -> None:
    """Draw the icons again if the theme's colors changed since they were drawn; a view calls it as it draws."""
    if _BadgeIconsState.previews is None:
        return
    theme_colors = _read_theme_colors()
    if theme_colors != _BadgeIconsState.drawn_theme_colors:
        _draw_icons(theme_colors)


def remove_icons() -> None:
    """Free the preview collection."""
    if _BadgeIconsState.previews is not None:
        bpy.utils.previews.remove(_BadgeIconsState.previews)
        _BadgeIconsState.previews = None
        _BadgeIconsState.drawn_theme_colors = None


def icon_id(badge: Badge, place: BadgePlace, is_greyed: bool) -> int:
    """The number a layout's `icon_value` takes for a badge in a place among its row's badges, greyed out or not."""
    return _BadgeIconsState.previews[_preview_name(badge, place, is_greyed)].icon_id
