"""Which children a prim tree lists, and how many a prim has."""

from __future__ import annotations

from pxr import Usd

# Every child a stage editor shows: inactive, unloaded, abstract (class), and undefined (over) prims, and the
# contents of native instances reached through instance proxies.
CHILD_PREDICATE = Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)


def child_count(prim: Usd.Prim) -> int:
    """How many children a prim tree lists under a prim: its children as `CHILD_PREDICATE` filters them."""
    return len(prim.GetFilteredChildren(CHILD_PREDICATE))
