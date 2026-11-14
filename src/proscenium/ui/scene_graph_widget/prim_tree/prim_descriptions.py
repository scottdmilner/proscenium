"""What a prim tree says about a prim: its row's name and badges, and the text of its tooltips and details.

It words what the tree has read (`RowDetails`, `PrimDetails`) and makes no USD queries of its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...widget_model import prim_detail_text

if TYPE_CHECKING:
    from ...widget_model.prim_details import PrimDetails, RowDetails

# What the tree's keys do, for the disclosure triangle's tooltip.
KEY_HINTS = "Right: expand, or step in    Left: collapse, or step out    Shift: the whole subtree"
# Unicode's mathematical sans-serif italic letters, the closest to Blender's UI font. A label can't set a font, so
# these stand in for italics; the block has no italic digits, so digits and other characters stay upright.
_SANS_ITALIC_CAPITAL_A = 0x1D608
_SANS_ITALIC_SMALL_A = 0x1D622


def _sans_italic(text: str) -> str:
    """Text with its ASCII letters as Unicode sans-serif italics, for display only."""
    return "".join(
        chr(_SANS_ITALIC_CAPITAL_A + ord(c) - ord("A"))
        if "A" <= c <= "Z"
        else chr(_SANS_ITALIC_SMALL_A + ord(c) - ord("a"))
        if "a" <= c <= "z"
        else c
        for c in text
    )


def row_name(details: RowDetails, shows_display_name: bool) -> str:
    """The name a row draws: its displayName where shown and authored, else its name, in italics for a class.

    Only drawn: copying, search, and tooltips use the prim's own name and path.
    """
    name = (shows_display_name and details.display_name) or details.name
    return _sans_italic(name) if details.is_class else name


def row_tooltip(details: RowDetails, prim_details: PrimDetails) -> str:
    """A row's tooltip: the prim's path, type, specifier, anything unusual about it, and what each badge stands for.

    The badges are labels, which have no tooltips of their own, so the row's says what they mark.
    """
    lines = [str(details.path), f"{details.type_name or 'No type'}, {details.specifier.displayName}"]
    if not details.is_active:
        lines.append(prim_detail_text.INACTIVE_LINE)
    if details.model_kind:
        lines.append(f"Kind: {details.model_kind}")
    if details.is_invalid_model:
        lines.append(prim_detail_text.INVALID_MODEL_LINE)
    if prim_detail_text.has_instance_badge(details):
        lines.append(prim_detail_text.instance_line(details, prim_details))
    lines.extend(prim_detail_text.arc_line(details, prim_details, arc) for arc in prim_detail_text.row_arcs(details))
    if details.is_instance_proxy:
        lines.append(prim_detail_text.instance_proxy_line(details))
    return "\n".join(lines)


def disclosure_tooltip(details: RowDetails, is_expanded: bool) -> str:
    """The disclosure triangle's tooltip: what a click does to the row, and the keys that do the same."""
    action = "Collapse" if is_expanded else "Expand"
    return f"{action} {details.name}. Shift-click: the whole subtree.\nKeys: {KEY_HINTS}"


def details_lines(details: RowDetails, prim_details: PrimDetails) -> list[str]:
    """The details panel's lines for a prim."""
    arcs = [
        name
        for name, has in (
            ("references", details.has_references),
            ("payload", details.has_payload),
            ("inherits", details.has_inherits),
            ("specializes", details.has_specializes),
        )
        if has
    ]
    return [
        str(details.path),
        f"Type: {details.type_name or '(none)'}   Specifier: {details.specifier.displayName}",
        f"Active: {details.is_active}   Loaded: {details.is_loaded}   Kind: {details.model_kind}",
        f"Instance: {details.is_instance}   Instance proxy: {details.is_instance_proxy}",
        f"Arcs: {', '.join(arcs) or 'none'}",
        *(f"Variant {name} = {selection}" for name, selection in prim_details.variant_selections),
        f"{prim_details.authored_attribute_count} authored attributes, {details.child_count} children",
    ]
