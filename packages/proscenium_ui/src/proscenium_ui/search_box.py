"""A widget's search box: its text field, its match mode, a case toggle, and any toggles of the widget's own.

The box draws a property group's `search_text`, `search_mode` (an enum of `match_mode_items`), and
`search_case_sensitive`, which a widget's properties define with their own update callbacks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .columned_list import column_layout
from .widget_model import text_matching

if TYPE_CHECKING:
    from collections.abc import Sequence

    import bpy
    from bpy.stub_internal.rna_enums import IconItems

SEARCH_MODE_UNITS = 6.0  # the match dropdown, wide enough for its longest mode, "Path contains"
SEARCH_TOGGLE_UNITS = 1.0  # each toggle after it, an icon button's width
SEARCH_TEXT_LEAST_FACTOR = 0.4  # the text field's share of the search row in a region too narrow for the rest


def match_mode_items() -> list[tuple[str, str, str]]:
    """The search_mode enum's items: each match mode, by its name, labeled with its value."""
    return [(mode.name, mode.value.capitalize(), "") for mode in text_matching.MatchMode]


def draw_search_box(
    layout: bpy.types.UILayout,
    context: bpy.types.Context,
    properties: Any,
    placeholder: str,
    toggles: Sequence[tuple[str, IconItems]] = (),
) -> None:
    """Draw the search box, with a toggle after the case toggle for each (boolean property, icon) in toggles."""
    # The text field takes what the mode and toggles leave; in a row, every item would grow with the width.
    options_units = SEARCH_MODE_UNITS + (1 + len(toggles)) * SEARCH_TOGGLE_UNITS
    text_factor = column_layout.split_factor_leaving(context, options_units, SEARCH_TEXT_LEAST_FACTOR)
    split = layout.split(factor=text_factor, align=True)
    split.row(align=True).prop(properties, "search_text", text="", icon="VIEWZOOM", placeholder=placeholder)
    options = split.row(align=True)
    options.prop(properties, "search_mode", text="")
    # As wide as the icon-only toggles after it.
    column_layout.fixed_width(options, SEARCH_TOGGLE_UNITS).prop(
        properties, "search_case_sensitive", text="Aa", toggle=True
    )
    for property_name, icon in toggles:
        column_layout.fixed_width(options, SEARCH_TOGGLE_UNITS).prop(
            properties, property_name, text="", icon=icon, toggle=True
        )
