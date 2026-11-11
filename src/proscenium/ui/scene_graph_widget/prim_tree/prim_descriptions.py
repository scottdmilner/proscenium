"""What a prim tree says about a prim: its row's name and badges, and the text of its tooltips and details."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from pxr import Usd

from .prim_children import CHILD_PREDICATE
from .prim_tree import is_invalid_model

if TYPE_CHECKING:
    from .prim_tree import RowDetails

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
    """A composition fact a row marks with an icon."""

    PAYLOAD = "payload"
    REFERENCES = "references"
    VARIANTS = "variants"
    INSTANCE = "instance"  # an instance, or a prim inside one (an instance proxy)


def row_badges(details: RowDetails) -> list[Badge]:
    """The badges a row shows, in drawing order."""
    shown = (
        (Badge.PAYLOAD, details.has_payload),
        (Badge.REFERENCES, details.has_references),
        (Badge.VARIANTS, details.has_variants),
        (Badge.INSTANCE, details.is_instance or details.is_instance_proxy),
    )
    return [badge for badge, is_shown in shown if is_shown]


def row_tooltip(prim: Usd.Prim) -> str:
    """A row's tooltip: the prim's path, type, specifier, and anything unusual about it."""
    lines = [str(prim.GetPath()), f"{prim.GetTypeName() or 'No type'}, {prim.GetSpecifier().displayName}"]
    if not prim.IsActive():
        lines.append("Inactive")
    model_kind = Usd.ModelAPI(prim).GetKind()
    if model_kind:
        lines.append(f"Kind: {model_kind}")
    if is_invalid_model(prim):
        lines.append("Not a model: an ancestor isn't a group or assembly")
    return "\n".join(lines)


def disclosure_tooltip(prim: Usd.Prim, is_expanded: bool) -> str:
    """The disclosure triangle's tooltip: what a click does to the row, and the keys that do the same."""
    action = "Collapse" if is_expanded else "Expand"
    return f"{action} {prim.GetName()}. Shift-click: the whole subtree.\nKeys: {KEY_HINTS}"


def _arc_targets(prim: Usd.Prim, list_name: str) -> list[str]:
    """The targets a prim's specs author for references or payloads, as asset@prim strings."""
    arcs = [arc for spec in prim.GetPrimStack() for arc in getattr(spec, list_name).ApplyEditsToList([])]
    return [f"@{arc.assetPath}@{arc.primPath}" if arc.assetPath else str(arc.primPath) for arc in arcs]


def badge_tooltip(prim: Usd.Prim, badge: Badge) -> str:
    """What a badge says about its prim when hovered."""
    if badge is Badge.PAYLOAD:
        state = "loaded" if prim.IsLoaded() else "unloaded"
        return f"Payload ({state}): {', '.join(_arc_targets(prim, 'payloadList'))}"
    if badge is Badge.REFERENCES:
        return f"References: {', '.join(_arc_targets(prim, 'referenceList'))}"
    if badge is Badge.VARIANTS:
        variant_sets = prim.GetVariantSets()
        names = variant_sets.GetNames()
        return "Variants: " + ", ".join(f"{n} = {variant_sets.GetVariantSelection(n) or '(none)'}" for n in names)
    if prim.IsInstanceProxy():
        return f"Inside an instance; prototype prim {prim.GetPrimInPrototype().GetPath()}"
    return f"Instance of prototype {prim.GetPrototype().GetPath()}"


def details_lines(prim: Usd.Prim) -> list[str]:
    """The details panel's lines for a prim."""
    arcs = [
        name
        for name, has in (
            ("references", prim.HasAuthoredReferences()),
            ("payload", prim.HasPayload()),
            ("inherits", prim.HasAuthoredInherits()),
            ("specializes", prim.HasAuthoredSpecializes()),
        )
        if has
    ]
    variant_sets = prim.GetVariantSets()
    children = prim.GetFilteredChildren(CHILD_PREDICATE)  # instance proxies count
    return [
        str(prim.GetPath()),
        f"Type: {prim.GetTypeName() or '(none)'}   Specifier: {prim.GetSpecifier().displayName}",
        f"Active: {prim.IsActive()}   Loaded: {prim.IsLoaded()}   Kind: {Usd.ModelAPI(prim).GetKind()}",
        f"Instance: {prim.IsInstance()}   Instance proxy: {prim.IsInstanceProxy()}",
        f"Arcs: {', '.join(arcs) or 'none'}",
        *(f"Variant {name} = {variant_sets.GetVariantSelection(name)}" for name in variant_sets.GetNames()),
        f"{len(prim.GetAuthoredAttributes())} authored attributes, {len(children)} children",
    ]
