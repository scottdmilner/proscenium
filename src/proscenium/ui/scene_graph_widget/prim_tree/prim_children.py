"""Which children a prim tree lists, and whether a prim has any."""

from __future__ import annotations

from pxr import Usd

# Every child a stage editor shows: inactive, unloaded, abstract (class), and undefined (over) prims, and the
# contents of native instances reached through instance proxies.
CHILD_PREDICATE = Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)


def has_children(prim: Usd.Prim) -> bool:
    """Whether a prim has any child, without listing them all (a list of names costs the size of the group)."""
    descendants = iter(Usd.PrimRange(prim, CHILD_PREDICATE))
    next(descendants)  # the prim itself
    return next(descendants, None) is not None
