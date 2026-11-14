"""What the widgets say about a prim alike, worded from what they read of it (`prim_details`): its badges, and lines.

A prim's badges are its instancing and the composition arcs authored on it, each in effect or not; its lines say what
each badge marks (an instance's prototype, an arc's targets), and what's unusual about it (inactive, an invalid model,
an instance proxy). The scene graph's row tooltip and the property viewer's summary both say them so. It makes no USD
queries of its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .composition_arcs import CompositionArc

if TYPE_CHECKING:
    from .prim_details import PrimDetails, RowDetails

# What a prim's tooltip or summary says of an inactive prim, and of a prim whose kind its ancestors don't support.
INACTIVE_LINE = "Inactive"
INVALID_MODEL_LINE = "Not a model: an ancestor isn't a group or assembly"


def has_instance_badge(details: RowDetails) -> bool:
    """Whether a row shows the instance badge, ahead of its arcs': for an instance, or a prim marked instanceable."""
    return details.is_instance or details.is_instanceable


def is_instance_badge_in_effect(details: RowDetails) -> bool:
    """Whether the instance badge marks an instance; instanceable metadata alone leaves the prim none, greyed out."""
    return details.is_instance


def row_arcs(details: RowDetails) -> list[CompositionArc]:
    """The composition arcs authored on a row's prim, which its badges mark, strongest first."""
    authored = {
        CompositionArc.INHERITS: details.has_inherits,
        CompositionArc.VARIANTS: details.has_variants,
        CompositionArc.REFERENCES: details.has_references,
        CompositionArc.PAYLOAD: details.has_payload,
        CompositionArc.SPECIALIZES: details.has_specializes,
    }
    return [arc for arc in CompositionArc if authored[arc]]


def is_arc_in_effect(details: RowDetails, arc: CompositionArc) -> bool:
    """Whether an arc authored on the prim contributes to it now; a row greys out the badge of one that doesn't.

    A payload left unloaded doesn't, nor do variant sets none of which has a variant selected.
    """
    if arc is CompositionArc.PAYLOAD:
        return details.is_loaded
    if arc is CompositionArc.VARIANTS:
        return details.has_variant_selection
    return True


def instance_proxy_line(details: RowDetails) -> str:
    """The line saying an instance proxy is one, and which instance it's inside."""
    return f"Instance proxy, read-only: inside instance {details.instance_path}"


def instance_line(details: RowDetails, prim_details: PrimDetails) -> str:
    """The line for a prim's instance badge, in its row's tooltip or a summary: its prototype, or why it has none."""
    if details.is_instance:
        return f"Instance of {prim_details.prototype_path}"
    if not details.is_active:
        return "Instanceable, but not an instance: it's inactive"
    if not _has_composition_arcs(details):
        return "Instanceable, but not an instance: it has no composition arcs"
    return "Instanceable, but not an instance"


def arc_line(details: RowDetails, prim_details: PrimDetails, arc: CompositionArc) -> str:
    """The line for a prim's arc badge, in its row's tooltip or a summary: the arc's targets."""
    if arc is CompositionArc.INHERITS:
        return f"Inherits: {', '.join(prim_details.inherit_paths)}"
    if arc is CompositionArc.VARIANTS:
        selections = prim_details.variant_selections
        return "Variants: " + ", ".join(f"{name} = {selection or '(none)'}" for name, selection in selections)
    if arc is CompositionArc.REFERENCES:
        return f"References: {', '.join(prim_details.reference_targets)}"
    if arc is CompositionArc.PAYLOAD:
        state = "loaded" if details.is_loaded else "unloaded"
        return f"Payload ({state}): {', '.join(prim_details.payload_targets)}"
    return f"Specializes: {', '.join(prim_details.specialize_paths)}"


def _has_composition_arcs(details: RowDetails) -> bool:
    return (
        details.has_inherits
        or details.has_variants
        or details.has_references
        or details.has_payload
        or details.has_specializes
    )
