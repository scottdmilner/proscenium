"""The property viewer's summary of its prim, above the list: what the scene graph's tooltip says of it, compacted.

Its path; its type, specifier, and kind on one line; anything unusual about it (inactive, an invalid model, an
instance proxy); and its instancing and composition arcs, a line each led by the badge the scene graph draws for it,
greyed out as the scene graph greys it. The lines are worded as the scene graph's are, by what the widgets share
(`widget_model.prim_detail_text`, from `widget_model.prim_details`), read once per list, so again after any stage
change that touches the prim.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from ... import text_wrapping
from ...widget_model import prim_detail_text
from ...widget_model.prim_details import prim_details_of, row_details_of
from ...widget_resources import badge_icons

if TYPE_CHECKING:
    import bpy

    from ...widget_model.prim_details import PrimDetails, RowDetails
    from ..property_list import PropertyList
    from .property_viewer_views import PropertyViewerView

# The summary's line height, as a share of a row's, and the metadata panel's: their lines are text, so they needn't
# stand a button's height apart.
LINE_SCALE = 0.75
GAP_FACTOR = 0.5  # the separator after the summary, before the list's header


class SummaryLine(NamedTuple):
    """One line of a prim's summary: its text, and the badge before it, greyed out if what it marks isn't in effect."""

    text: str
    badge_look: badge_icons.BadgeLook | None = None
    is_in_effect: bool = True


def summary_lines(details: RowDetails, prim_details: PrimDetails) -> list[SummaryLine]:
    """A prim's summary, a line each: path; type, specifier, and kind; anything unusual; its instancing and arcs."""
    facts = [f"Type: {details.type_name or 'none'}", f"Spec: {details.specifier.displayName}"]
    if details.model_kind:
        facts.append(f"Kind: {details.model_kind}")
    lines = [SummaryLine(str(details.path)), SummaryLine("   ".join(facts))]
    if not details.is_active:
        lines.append(SummaryLine(prim_detail_text.INACTIVE_LINE))
    if details.is_invalid_model:
        lines.append(SummaryLine(prim_detail_text.INVALID_MODEL_LINE))
    if details.is_instance_proxy:
        lines.append(SummaryLine(prim_detail_text.instance_proxy_line(details)))
    if prim_detail_text.has_instance_badge(details):
        lines.append(
            SummaryLine(
                prim_detail_text.instance_line(details, prim_details),
                badge_icons.INSTANCE_BADGE_LOOK,
                prim_detail_text.is_instance_badge_in_effect(details),
            )
        )
    lines.extend(
        SummaryLine(
            prim_detail_text.arc_line(details, prim_details, arc),
            badge_icons.ARC_LOOKS[arc],
            prim_detail_text.is_arc_in_effect(details, arc),
        )
        for arc in prim_detail_text.row_arcs(details)
    )
    return lines


class _PrimSummaryState:
    """Each view's summary, by view name, with the list it was read for: read again once a new list replaces it."""

    lines_by_view_name: dict[str, tuple[PropertyList, list[SummaryLine]]] = {}


def view_summary_lines(view: PropertyViewerView, property_list: PropertyList) -> list[SummaryLine]:
    """The summary of a view's list's prim, read once per list."""
    cached = _PrimSummaryState.lines_by_view_name.get(view.name)
    if cached is not None and cached[0] is property_list:
        return cached[1]
    stage = view.property_list_view.stage()
    prim = stage.GetPrimAtPath(property_list.prim_path) if stage is not None else None
    if prim is None or not prim:
        return []
    lines = summary_lines(row_details_of(prim), prim_details_of(prim))
    _PrimSummaryState.lines_by_view_name[view.name] = (property_list, lines)
    return lines


def forget_summary(view_name: str) -> None:
    """Drop a view's cached summary, as when the view is removed."""
    _PrimSummaryState.lines_by_view_name.pop(view_name, None)


def draw_summary(
    layout: bpy.types.UILayout, context: bpy.types.Context, view: PropertyViewerView, property_list: PropertyList
) -> None:
    """Draw the summary of a view's prim, its lines closer together than rows; the badges' icons must be drawn.

    A line too long for the region wraps onto the next, so its paths show whole.
    """
    column = layout.column(align=True)
    column.scale_y = LINE_SCALE
    for line in view_summary_lines(view, property_list):
        icon_value = None
        if line.badge_look is not None:
            place = badge_icons.BadgePlace.ALONE
            icon_value = badge_icons.icon_id(line.badge_look, place, is_greyed=not line.is_in_effect)
        text_wrapping.draw_wrapped_label(column, context, line.text, icon_value)
    layout.separator(factor=GAP_FACTOR)
