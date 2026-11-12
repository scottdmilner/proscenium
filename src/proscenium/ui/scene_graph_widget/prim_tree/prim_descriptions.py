"""What a prim tree says about a prim: its row's name and badges, and the text of its tooltips and details.

It words what the tree has read (`RowDetails`, `PrimDetails`) and makes no USD queries of its own.
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .prim_tree import PrimDetails, RowDetails

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


class Badge(enum.Enum):
    """A mark after a prim's name: instancing, then each composition arc authored on it, by its letter.

    The arcs in LIVRPS strength order, strongest first (local opinions, the L, have none), as a row draws them.
    """

    INHERITS = "inherits"
    VARIANTS = "variants"
    REFERENCES = "references"
    PAYLOAD = "payload"
    SPECIALIZES = "specializes"
    INSTANCE = "instance"  # an instance, or a prim marked instanceable that isn't one


def row_badges(details: RowDetails) -> list[Badge]:
    """The badges a row shows, in drawing order."""
    shown = (
        (Badge.INSTANCE, details.is_instance or details.is_instanceable),
        (Badge.INHERITS, details.has_inherits),
        (Badge.VARIANTS, details.has_variants),
        (Badge.REFERENCES, details.has_references),
        (Badge.PAYLOAD, details.has_payload),
        (Badge.SPECIALIZES, details.has_specializes),
    )
    return [badge for badge, is_shown in shown if is_shown]


def is_badge_in_effect(details: RowDetails, badge: Badge) -> bool:
    """Whether a badge's arc contributes to the prim now; a row greys out a badge that doesn't.

    A payload left unloaded doesn't, nor do variant sets none of which has a variant selected, nor instanceable
    metadata on a prim without composition arcs, which leaves it no instance.
    """
    if badge is Badge.INSTANCE:
        return details.is_instance
    if badge is Badge.PAYLOAD:
        return details.is_loaded
    if badge is Badge.VARIANTS:
        return details.has_variant_selection
    return True


def row_tooltip(details: RowDetails, prim_details: PrimDetails) -> str:
    """A row's tooltip: the prim's path, type, specifier, anything unusual about it, and what each badge stands for.

    The badges are labels, which have no tooltips of their own, so the row's says what they mark.
    """
    lines = [str(details.path), f"{details.type_name or 'No type'}, {details.specifier.displayName}"]
    if not details.is_active:
        lines.append("Inactive")
    if details.model_kind:
        lines.append(f"Kind: {details.model_kind}")
    if details.is_invalid_model:
        lines.append("Not a model: an ancestor isn't a group or assembly")
    lines.extend(_badge_line(details, prim_details, badge) for badge in row_badges(details))
    if details.is_instance_proxy:
        lines.append(f"Instance proxy, read-only: inside instance {details.instance_path}")
    return "\n".join(lines)


def disclosure_tooltip(details: RowDetails, is_expanded: bool) -> str:
    """The disclosure triangle's tooltip: what a click does to the row, and the keys that do the same."""
    action = "Collapse" if is_expanded else "Expand"
    return f"{action} {details.name}. Shift-click: the whole subtree.\nKeys: {KEY_HINTS}"


def _badge_line(details: RowDetails, prim_details: PrimDetails, badge: Badge) -> str:
    """The row tooltip's line for a badge: its arc's targets."""
    if badge is Badge.INHERITS:
        return f"Inherits: {', '.join(prim_details.inherit_paths)}"
    if badge is Badge.VARIANTS:
        selections = prim_details.variant_selections
        return "Variants: " + ", ".join(f"{name} = {selection or '(none)'}" for name, selection in selections)
    if badge is Badge.REFERENCES:
        return f"References: {', '.join(prim_details.reference_targets)}"
    if badge is Badge.PAYLOAD:
        state = "loaded" if details.is_loaded else "unloaded"
        return f"Payload ({state}): {', '.join(prim_details.payload_targets)}"
    if badge is Badge.INSTANCE:
        if details.is_instance:
            return f"Instance of {prim_details.prototype_path}"
        if not details.is_active:
            return "Instanceable, but not an instance: it's inactive"
        if not _has_composition_arcs(details):
            return "Instanceable, but not an instance: it has no composition arcs"
        return "Instanceable, but not an instance"
    return f"Specializes: {', '.join(prim_details.specialize_paths)}"


def _has_composition_arcs(details: RowDetails) -> bool:
    return (
        details.has_inherits
        or details.has_variants
        or details.has_references
        or details.has_payload
        or details.has_specializes
    )


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
