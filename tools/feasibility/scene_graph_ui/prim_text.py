"""What the tree's tooltips and details panel say about a prim. Nothing here imports bpy."""

from __future__ import annotations

from pxr import Usd
from tree_model import CHILD_PREDICATE


def row_tooltip(prim: Usd.Prim) -> str:
    """A row's tooltip: the prim's path, type, specifier, and anything unusual about it."""
    lines = [str(prim.GetPath()), f"{prim.GetTypeName() or 'No type'}, {prim.GetSpecifier().displayName}"]
    if not prim.IsActive():
        lines.append("Inactive")
    kind = Usd.ModelAPI(prim).GetKind()
    if kind:
        lines.append(f"Kind: {kind}")
    return "\n".join(lines)


def _arc_targets(prim: Usd.Prim, list_name: str) -> list[str]:
    """The targets a prim's specs author for references or payloads, as asset@prim strings."""
    arcs = [arc for spec in prim.GetPrimStack() for arc in getattr(spec, list_name).ApplyEditsToList([])]
    return [f"@{arc.assetPath}@{arc.primPath}" if arc.assetPath else str(arc.primPath) for arc in arcs]


def badge_tooltip(prim: Usd.Prim, badge: str) -> str:
    """What a badge says about its prim when hovered."""
    if badge == "payload":
        state = "loaded" if prim.IsLoaded() else "unloaded"
        return f"Payload ({state}): {', '.join(_arc_targets(prim, 'payloadList'))}"
    if badge == "references":
        return f"References: {', '.join(_arc_targets(prim, 'referenceList'))}"
    if badge == "variants":
        variant_sets = prim.GetVariantSets()
        names = variant_sets.GetNames()
        return "Variants: " + ", ".join(f"{n} = {variant_sets.GetVariantSelection(n) or '(none)'}" for n in names)
    if prim.IsInstanceProxy():
        return f"Inside an instance; prototype prim {prim.GetPrimInPrototype().GetPath()}"
    return f"Instance of prototype {prim.GetPrototype().GetPath()}"


def details_lines(prim: Usd.Prim) -> list[str]:
    """The details panel's lines for the selected prim."""
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
