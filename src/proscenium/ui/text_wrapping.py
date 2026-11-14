"""Wrapping a label's text to its region's width: Blender cuts the middle out of text too long for a label.

A label has no wrapping, and shortens what doesn't fit it with an ellipsis, which hides the part of a long path that
tells it apart. Text that must be read whole is split into lines that fit instead: each line ends at the last break
that fits, after a slash, dot, colon, comma, or space, so a path breaks between its elements, and a part too long for
a line with no break in it is cut where it fills the line. The text's width is measured with `blf` in the UI font at
the UI's scale; without a region to measure against, as in background mode, text isn't wrapped.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import blf

from .columned_list import column_layout

if TYPE_CHECKING:
    from collections.abc import Callable

    import bpy

UI_FONT_ID = 0  # blf's default font, the UI's
# What a label's own padding and a rounding margin take from the row's width, in UI units, so a line measured to fit
# is never one Blender shortens.
LABEL_PADDING_UNITS = 1.0
ICON_UNITS = 1.0  # what a label's icon, and the gap after it, take from its text's width
_BREAKS = re.compile(r"(?<=[/.:, ])")  # a split after each break character, which stays with the line it ends


def wrap_text(text: str, width: float, text_width: Callable[[str], float]) -> list[str]:
    """Text split into lines no wider than width, as text_width measures them, breaking after a break character.

    A part with no break narrower than width is cut where it fills a line. A width too small for one character
    keeps one character a line.
    """
    lines: list[str] = []
    current = ""
    for part in _BREAKS.split(text):
        if current and text_width(current + part) > width:
            lines.append(current.rstrip())
            current = part.lstrip()
        else:
            current += part
        while len(current) > 1 and text_width(current) > width:
            cut = max(1, _fitting_length(current, width, text_width))
            lines.append(current[:cut])
            current = current[cut:]
    if current or not lines:
        lines.append(current)
    return lines


def _fitting_length(text: str, width: float, text_width: Callable[[str], float]) -> int:
    """How many of text's first characters fit in width, by bisection: widths grow with each character."""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if text_width(text[:middle]) <= width:
            low = middle
        else:
            high = middle - 1
    return low


def _label_text_width(context: bpy.types.Context, units_before_text: float) -> float | None:
    """The pixels a label's text has in a panel row, after units_before_text; None without a region to measure."""
    width_units = column_layout.row_units(context)
    if width_units is None:
        return None
    return (width_units - LABEL_PADDING_UNITS - units_before_text) * column_layout.unit_pixels(context)


def _ui_text_width(context: bpy.types.Context) -> Callable[[str], float]:
    """A measure of text in pixels, in the UI's font at its size and scale."""
    preferences = context.preferences
    if preferences is not None:
        blf.size(UI_FONT_ID, preferences.ui_styles[0].widget.points * preferences.system.ui_scale)

    def text_width(text: str) -> float:
        return blf.dimensions(UI_FONT_ID, text)[0]

    return text_width


def wrapped_lines(context: bpy.types.Context, text: str, has_icon: bool = False) -> list[str]:
    """A label's text as the lines that fit its region's width, after an icon if it has one; whole without a region."""
    width = _label_text_width(context, ICON_UNITS if has_icon else 0.0)
    if width is None or width <= 0:
        return [text]
    return wrap_text(text, width, _ui_text_width(context))


def draw_wrapped_label(
    layout: bpy.types.UILayout, context: bpy.types.Context, text: str, icon_value: int | None = None
) -> None:
    """Draw text as labels that fit the region's width, the first after an icon, the rest indented past it."""
    for line_index, line in enumerate(wrapped_lines(context, text, has_icon=icon_value is not None)):
        if icon_value is None:
            layout.label(text=line)
        elif line_index == 0:
            layout.label(text=line, icon_value=icon_value)
        else:
            layout.label(text=line, icon="BLANK1")  # under the first line's text, past its icon
