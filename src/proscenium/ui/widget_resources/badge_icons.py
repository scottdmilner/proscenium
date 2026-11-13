"""Badge icons for list rows, drawn into a preview collection from pixels made here, so they need no files.

A badge is a glyph, a composition arc's bold LIVRPS letter or an instance's two overlapping squares
(`INSTANCE_GLYPH`), in one of the theme's collection colors (a `BadgeLook`), on its piece of a dark rounded block: a
row's badges are labels side by side, so the block is drawn into their icons, each badge drawing the piece for its
place in the row (`BadgePlace`). The block takes the theme's pie menu color and roundness, the dark of a PIE_MENU
button. A badge that isn't in effect is greyed out: its glyph is the pie menu's text color, half blended into the
block. Each badge's icon is drawn the first time it's asked for; preview icons keep the colors they're drawn in, so
every icon drawn is drawn again when the theme's colors change (`redraw_icons_if_theme_changed`); they're read in
`theme_colors`. A layout takes the icons by number (`icon_value=icon_id(...)`), not by Blender's icon names. In
background mode, previews get number 0.
"""

from __future__ import annotations

import enum
import math
from typing import Any, NamedTuple

import bpy
import bpy.utils.previews

from ..widget_model.composition_arcs import CompositionArc
from . import theme_colors
from .theme_colors import RGB, RGBA, CollectionColor, ThemeColors

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
INSTANCE_GLYPH = "⧉"  # an instance badge's: two overlapping squares, for the copies sharing one prototype


def _square_outlines(*squares: tuple[Point, Point]) -> tuple[Segment, ...]:
    """The four sides of each square, given by its lower left and upper right corners."""
    sides: list[Segment] = []
    for (left, bottom), (right, top) in squares:
        sides += [((left, bottom), (right, bottom)), ((right, bottom), (right, top))]
        sides += [((right, top), (left, top)), ((left, top), (left, bottom))]
    return tuple(sides)


GLYPH_STROKES: dict[str, tuple[Segment | Arc, ...]] = {
    "I": (((0.0, -0.75), (0.0, 0.75)), ((-0.3, 0.75), (0.3, 0.75)), ((-0.3, -0.75), (0.3, -0.75))),
    "V": (((-0.57, 0.75), (0.0, -0.75)), ((0.0, -0.75), (0.57, 0.75))),  # wider than the others, as a V is
    "R": (*_P_BOWL, ((0.0, -0.05), (0.45, -0.75))),
    "P": _P_BOWL,
    "S": (
        ((0.0, (0.75 + _S_MIDDLE) / 2), (0.75 - _S_MIDDLE) / 2, 20.0, 270.0),
        ((0.0, (_S_MIDDLE - 0.75) / 2), (0.75 + _S_MIDDLE) / 2, -160.0, 90.0),
    ),
    INSTANCE_GLYPH: _square_outlines(((-0.55, -0.05), (0.2, 0.7)), ((-0.2, -0.7), (0.55, 0.05))),
}
# A glyph's stroke half width where it isn't STROKE_HALF_WIDTH: the instance glyph's squares are finer, so the
# space inside them stays open.
STROKE_HALF_WIDTHS = {INSTANCE_GLYPH: 0.11}

GREYED_LETTER_WEIGHT = 0.5  # how much of a greyed-out glyph's color is the pie menu's text color, the rest the block's


class BadgeLook(NamedTuple):
    """How a badge looks: its glyph, one of GLYPH_STROKES', in one of the theme's collection colors."""

    color: CollectionColor
    glyph: str


# Each arc's badge, its letter in a collection color of its own. Red and brown go unused: brown is too dark on the
# block.
ARC_LOOKS: dict[CompositionArc, BadgeLook] = {
    CompositionArc.INHERITS: BadgeLook(CollectionColor.PINK, "I"),
    CompositionArc.VARIANTS: BadgeLook(CollectionColor.VIOLET, "V"),
    CompositionArc.REFERENCES: BadgeLook(CollectionColor.ORANGE, "R"),
    CompositionArc.PAYLOAD: BadgeLook(CollectionColor.YELLOW, "P"),
    CompositionArc.SPECIALIZES: BadgeLook(CollectionColor.BLUE, "S"),
}


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


Coverages = tuple[tuple[float, float], ...]  # each pixel's letter and block coverage, bottom row first


class _BadgeIconsState:
    """The preview collection, while registered, its icons, the theme colors they were drawn in, and their shapes."""

    previews: Any = None
    drawn_icons: dict[str, tuple[BadgeLook, BadgePlace, bool]] = {}  # by preview name: its look, place, and greying
    drawn_theme_colors: ThemeColors | None = None
    # Each badge's coverages at one block roundness, the theme's last: the shapes don't change with the colors, so
    # drawing the icons in new ones needn't work them out again; a new roundness replaces them all.
    coverages_roundness: float | None = None
    coverages_by_shape: dict[tuple[str, BadgePlace], Coverages] = {}


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
    return min(_stroke_distance(x, y, stroke) for stroke in GLYPH_STROKES[letter])


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


def _coverages(letter: str, place: BadgePlace, block_roundness: float) -> Coverages:
    """How much of each pixel a badge's letter and its piece of the block cover, kept for the last roundness."""
    if block_roundness != _BadgeIconsState.coverages_roundness:
        _BadgeIconsState.coverages_by_shape = {}
        _BadgeIconsState.coverages_roundness = block_roundness
    found = _BadgeIconsState.coverages_by_shape.get((letter, place))
    if found is None:
        found = _BadgeIconsState.coverages_by_shape[letter, place] = _shape_coverages(letter, place, block_roundness)
    return found


def _shape_coverages(letter: str, place: BadgePlace, block_roundness: float) -> Coverages:
    pixel_width = 2 / ICON_SIZE_PIXELS
    coverages: list[tuple[float, float]] = []
    for row in range(ICON_SIZE_PIXELS):
        for column in range(ICON_SIZE_PIXELS):
            x = (column + 0.5) * pixel_width - 1
            y = (row + 0.5) * pixel_width - 1
            letter_distance = _letter_distance(letter, x / LETTER_SCALE, y / LETTER_SCALE) * LETTER_SCALE
            half_width = STROKE_HALF_WIDTHS.get(letter, STROKE_HALF_WIDTH)
            letter_coverage = _coverage(letter_distance - half_width * LETTER_SCALE, pixel_width)
            block_coverage = _coverage(_block_distance(x, y, place, block_roundness), pixel_width)
            coverages.append((letter_coverage, block_coverage))
    return tuple(coverages)


def _pixels(
    coverages: Coverages,
    letter_color: RGB,
    block_color: RGBA,
) -> list[float]:
    """A badge's pixels: its letter over its piece of the block, premultiplied, as previews take them."""
    pixels: list[float] = []
    for letter_alpha, block_coverage in coverages:
        under = block_coverage * block_color[3] * (1 - letter_alpha)  # the block where the letter doesn't cover it
        pixels.extend(
            (*(letter_color[i] * letter_alpha + block_color[i] * under for i in range(3)), letter_alpha + under)
        )
    return pixels


def _greyed_color(theme_colors: ThemeColors) -> RGB:
    """A greyed-out badge's letter: the pie menu's text color, half blended into the block."""
    text, block, weight = theme_colors.pie_menu_text_color, theme_colors.pie_menu_inner_color, GREYED_LETTER_WEIGHT
    red, green, blue = (weight * text[i] + (1 - weight) * block[i] for i in range(3))
    return red, green, blue


def _draw_icon(preview: Any, look: BadgeLook, place: BadgePlace, is_greyed: bool, colors: ThemeColors) -> None:
    letter_color = _greyed_color(colors) if is_greyed else colors.collection_color(look.color)
    coverages = _coverages(look.glyph, place, colors.pie_menu_roundness)
    preview.icon_pixels_float = _pixels(coverages, letter_color, colors.pie_menu_inner_color)


def _draw_icons(colors: ThemeColors) -> None:
    """Draw every icon drawn so far again, in the theme's colors."""
    for preview_name, (look, place, is_greyed) in _BadgeIconsState.drawn_icons.items():
        _draw_icon(_BadgeIconsState.previews[preview_name], look, place, is_greyed, colors)
    _BadgeIconsState.drawn_theme_colors = colors


def _preview_name(look: BadgeLook, place: BadgePlace, is_greyed: bool) -> str:
    return f"{ord(look.glyph):x}_{look.color.name}_{place.name}{'_greyed' if is_greyed else ''}"


def create_icons() -> None:
    """Create the preview collection the badges are drawn into as they're asked for."""
    _BadgeIconsState.previews = bpy.utils.previews.new()
    _BadgeIconsState.drawn_icons = {}
    _BadgeIconsState.drawn_theme_colors = theme_colors.read_theme_colors()


def redraw_icons_if_theme_changed() -> None:
    """Draw the icons again if the theme's colors, as last read, changed since they were drawn."""
    if _BadgeIconsState.previews is None:
        return
    colors = theme_colors.last_read_theme_colors()
    if colors != _BadgeIconsState.drawn_theme_colors:
        _draw_icons(colors)


def remove_icons() -> None:
    """Free the preview collection."""
    if _BadgeIconsState.previews is not None:
        bpy.utils.previews.remove(_BadgeIconsState.previews)
        _BadgeIconsState.previews = None
    _BadgeIconsState.drawn_icons = {}
    _BadgeIconsState.drawn_theme_colors = None
    _BadgeIconsState.coverages_roundness = None
    _BadgeIconsState.coverages_by_shape = {}


def icon_id(look: BadgeLook, place: BadgePlace, is_greyed: bool) -> int:
    """The number a layout's `icon_value` takes for a badge in a place among its row's badges, greyed out or not.

    Its icon is drawn the first time it's asked for, in the theme's colors as the icons were last drawn.
    """
    preview_name = _preview_name(look, place, is_greyed)
    previews = _BadgeIconsState.previews
    preview = previews.get(preview_name)
    if preview is None:
        preview = previews.new(preview_name)
        preview.icon_size = (ICON_SIZE_PIXELS, ICON_SIZE_PIXELS)
        colors = _BadgeIconsState.drawn_theme_colors or theme_colors.last_read_theme_colors()
        _draw_icon(preview, look, place, is_greyed, colors)
        _BadgeIconsState.drawn_icons[preview_name] = (look, place, is_greyed)
    return preview.icon_id
