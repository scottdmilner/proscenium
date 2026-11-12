"""The colors the widget draws its own marks in: the theme's, mixes of them for the rows, and icon pixels in them.

The widget draws its badges, tinted icons, and dashed guide lines itself, so they take the theme's colors from here:
the collection colors, the list's text color, and the pie menu's, which the badges' block is drawn in. The collection
colors don't read on a light theme's grey rows, and the list's text color does in any theme, so a color mixed toward
the text reads in both. A mix is greyer than its color; one that keeps the color's saturation at the mix's luminance
contrasts as much and reads as the color. An icon drawn in any color is named for its color, rounded, so a color
computed again names the same icon.
"""

from __future__ import annotations

import colorsys
import enum
from dataclasses import dataclass

import bpy
import numpy as np

RGB = tuple[float, float, float]
RGBA = tuple[float, float, float, float]
COLOR_DIGITS = 4  # a color's channels are rounded to this many digits to name its icons
LUMINANCE_SEARCH_STEPS = 30  # bisections finding a saturated mix, far finer than a color channel's 1/255


class CollectionColor(enum.IntEnum):
    """One of the theme's eight collection colors, by its index: COLLECTION_COLOR_01 is RED."""

    RED = 0
    ORANGE = 1
    YELLOW = 2
    GREEN = 3
    BLUE = 4
    VIOLET = 5
    PINK = 6
    BROWN = 7


# Instancing's color, the instance badge's too. How much of a row mark's color is the text's: an instance proxy's is
# closer to the text, fainter than its instance's, since it's shared from the prototype.
INSTANCING_COLOR = CollectionColor.GREEN
INSTANCE_TEXT_WEIGHT = 0.6
INSTANCE_PROXY_TEXT_WEIGHT = 0.75


@dataclass(frozen=True, slots=True)
class ThemeColors:
    """The theme's colors the widget draws in, compared to tell when what was drawn in them needs drawing again."""

    pie_menu_inner_color: RGBA
    pie_menu_roundness: float  # not a color, but the badges' block is drawn to it, so it changes them as one does
    pie_menu_text_color: RGB
    list_text_color: RGB  # a list row's text color, which reads on the rows in any theme
    collection_colors: tuple[RGB, ...]  # the eight, in CollectionColor's order

    def collection_color(self, color: CollectionColor) -> RGB:
        """One of the collection colors."""
        return self.collection_colors[color]


# Without preferences to read the theme from: the default theme's colors.
DEFAULT_THEME_COLORS = ThemeColors(
    pie_menu_inner_color=(0.094, 0.094, 0.094, 1.0),
    pie_menu_roundness=0.4,
    pie_menu_text_color=(0.851, 0.851, 0.851),
    list_text_color=(0.8, 0.8, 0.8),
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


class _ThemeColorsState:
    """The theme's colors as last read."""

    last_read: ThemeColors | None = None


def read_theme_colors() -> ThemeColors:
    """Read the theme's colors from the preferences, or the defaults where there are none, and keep them."""
    preferences = bpy.context.preferences
    if preferences is None:  # the context has none to read
        theme_colors = DEFAULT_THEME_COLORS
    else:
        theme = preferences.themes[0]
        pie_menu = theme.user_interface.wcol_pie_menu
        list_text = theme.user_interface.wcol_list_item.text
        theme_colors = ThemeColors(
            pie_menu_inner_color=(pie_menu.inner[0], pie_menu.inner[1], pie_menu.inner[2], pie_menu.inner[3]),
            pie_menu_roundness=pie_menu.roundness,
            pie_menu_text_color=(pie_menu.text.r, pie_menu.text.g, pie_menu.text.b),
            list_text_color=(list_text.r, list_text.g, list_text.b),
            collection_colors=tuple((item.color.r, item.color.g, item.color.b) for item in theme.collection_color),
        )
    _ThemeColorsState.last_read = theme_colors
    return theme_colors


def last_read_theme_colors() -> ThemeColors:
    """The theme's colors as of the last read, at the last view's draw; the defaults before any."""
    return _ThemeColorsState.last_read or DEFAULT_THEME_COLORS


def relative_luminance(color: RGB) -> float:
    """A display color's relative luminance, as WCAG's contrast ratio weighs it."""

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = color
    return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)


def saturated_at_luminance(color: RGB, luminance: float) -> RGB:
    """The color's hue and saturation, made as light as the luminance, or mixed toward white where full value isn't."""
    hue, saturation, _ = colorsys.rgb_to_hsv(*color)
    brightest = colorsys.hsv_to_rgb(hue, saturation, 1.0)

    def shade(amount: float) -> RGB:  # 0 to 1: black to the brightest, then on to white
        if amount <= 1.0:
            return colorsys.hsv_to_rgb(hue, saturation, amount)
        white_weight = amount - 1.0
        red, green, blue = ((1 - white_weight) * channel + white_weight for channel in brightest)
        return red, green, blue

    low, high = 0.0, 2.0
    for _ in range(LUMINANCE_SEARCH_STEPS):  # luminance rises with the amount, so bisect for it
        middle = (low + high) / 2
        if relative_luminance(shade(middle)) < luminance:
            low = middle
        else:
            high = middle
    return shade((low + high) / 2)


def text_mix(color: RGB, text_weight: float) -> RGB:
    """The color mixed toward the list's text color, text_weight of it the text's, so it reads on the rows."""
    text_color = last_read_theme_colors().list_text_color
    red, green, blue = ((1 - text_weight) * color[i] + text_weight * text_color[i] for i in range(3))
    return red, green, blue


def saturated_text_mix(color: RGB, text_weight: float) -> RGB:
    """As light as the color's text mix, as saturated as the color: it contrasts as the mix does, in the color."""
    return saturated_at_luminance(color, relative_luminance(text_mix(color, text_weight)))


def instance_color() -> RGB:
    """The color an instance's row marks it in."""
    instancing_color = last_read_theme_colors().collection_color(INSTANCING_COLOR)
    return saturated_text_mix(instancing_color, INSTANCE_TEXT_WEIGHT)


def instance_proxy_color() -> RGB:
    """The color an instance proxy's row marks it in: fainter, for what it shares from its prototype."""
    instancing_color = last_read_theme_colors().collection_color(INSTANCING_COLOR)
    return text_mix(instancing_color, INSTANCE_PROXY_TEXT_WEIGHT)


def rounded_color(color: RGB) -> RGB:
    """A color with its channels rounded to COLOR_DIGITS, as it names its icons."""
    red, green, blue = color
    return round(red, COLOR_DIGITS), round(green, COLOR_DIGITS), round(blue, COLOR_DIGITS)


def color_name(color: RGB) -> str:
    """A rounded color's channels, joined to go in an icon's name."""
    return "_".join(str(channel) for channel in color)


def colored_pixels(coverages: np.ndarray, color: RGB) -> list[float]:
    """Pixels of a color, each as opaque as its coverage of 0 to 255, premultiplied, as previews take them."""
    alphas = coverages.astype(np.float32).ravel() / 255
    return np.column_stack([alphas * channel for channel in color] + [alphas]).ravel().tolist()
