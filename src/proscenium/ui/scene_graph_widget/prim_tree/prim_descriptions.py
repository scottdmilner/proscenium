"""What a prim tree says about a prim: its row's badges, and the text of its tooltips and details."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from pxr import Usd

from .prim_children import CHILD_PREDICATE

if TYPE_CHECKING:
    from .prim_tree import RowDetails

# What the tree's keys do, for the disclosure triangle's tooltip.
KEY_HINTS = "Right: expand, or step in    Left: collapse, or step out    Shift: the whole subtree"


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
