"""The composition arcs widgets mark, such as those authored on a prim."""

from __future__ import annotations

import enum


class CompositionArc(enum.Enum):
    """A composition arc, by the letter of LIVRPS after the L: local opinions come from no arc.

    Listed in LIVRPS strength order, strongest first, as widgets draw them.
    """

    INHERITS = "inherits"
    VARIANTS = "variants"
    REFERENCES = "references"
    PAYLOAD = "payload"
    SPECIALIZES = "specializes"
