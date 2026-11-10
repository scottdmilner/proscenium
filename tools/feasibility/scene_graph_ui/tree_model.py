"""A USD stage's prim hierarchy as the flat list of rows a tree widget shows.

Rows are spliced in on expand and cut out on collapse, so each costs the rows it adds or removes, and a row holds
only its prim and depth. What a row draws (`RowDetails`) is read from the prim when the row is first drawn, so the
widget pays for the rows on screen, not the rows in the list. Nothing here imports bpy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pxr import Sdf, Usd

if TYPE_CHECKING:
    import tree_search

# Every child a stage editor shows: inactive, unloaded, abstract (class), and undefined (over) prims, and the
# contents of native instances reached through instance proxies.
CHILD_PREDICATE = Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)


@dataclass(frozen=True, slots=True)
class TreeRow:
    """One visible prim and how deep it sits."""

    prim: Usd.Prim
    depth: int


@dataclass(frozen=True, slots=True)
class RowDetails:
    """The flags a row draws, read from its prim."""

    name: str
    type_name: str
    has_children: bool
    is_active: bool
    specifier: Sdf.Specifier
    has_payload: bool
    has_references: bool
    is_instance: bool
    is_instance_proxy: bool
    has_variants: bool


class StageTree:
    """The expansion state of one stage's hierarchy, and the rows it makes visible."""

    stage: Usd.Stage
    expanded: set[Usd.Prim]
    rows: list[TreeRow]
    version: int  # counts changes to rows, so a widget can cache what it computes from them
    search_result: tree_search.SearchResult | None  # the filter, while one is set
    _details: dict[Usd.Prim, RowDetails]
    _expanded_before_search: set[Usd.Prim]  # restored, with the selection revealed, when the filter clears

    def __init__(self, stage: Usd.Stage) -> None:
        self.stage = stage
        self.expanded = set()
        self._details = {}
        self.version = 0
        self.search_result = None
        self._expanded_before_search = set()
        self.rows = self._subtree_rows(stage.GetPseudoRoot(), -1)

    def set_search(self, result: tree_search.SearchResult | None, keep: Usd.Prim | None = None) -> None:
        """Show only a search's matches and their ancestors, expanded to reach them; None shows everything again.

        A match's own children all show when it is expanded, so a match can be explored from. Clearing the
        filter restores the expansion from before it, plus what reveals keep (the selection).
        """
        if result is not None:
            if self.search_result is None:
                self._expanded_before_search = set(self.expanded)
            self.expanded = {prim.GetParent() for prim in result.visible_prims}
        else:
            self.expanded = self._expanded_before_search if self.search_result is not None else self.expanded
        self.search_result = result
        self.rows = self._subtree_rows(self.stage.GetPseudoRoot(), -1)
        self.version += 1
        if result is None and keep is not None:
            self.reveal(keep)

    def is_match(self, row: TreeRow) -> bool:
        """Whether a row shows because it matched the filter (rather than holding a match), or no filter is set."""
        return self.search_result is None or row.prim in self.search_result.matching_prims

    def expand_or_enter_row(self, row_index: int) -> int:
        """Right arrow: expand a collapsed row, or move into an expanded one. Returns the row now active."""
        row = self.rows[row_index]
        if not self.details(row).has_children:
            return row_index
        if not self.is_expanded(row):
            self.toggle(row_index)
            return row_index
        has_visible_child = row_index + 1 < len(self.rows) and self.rows[row_index + 1].depth > row.depth
        return row_index + 1 if has_visible_child else row_index

    def collapse_or_select_parent(self, row_index: int) -> int:
        """Left arrow: collapse an expanded row, or move to its parent. Returns the row now active."""
        row = self.rows[row_index]
        if self.is_expanded(row) and self.details(row).has_children:
            self.toggle(row_index)
            return row_index
        parent = row_index - 1
        while parent >= 0 and self.rows[parent].depth >= row.depth:
            parent -= 1
        return parent if parent >= 0 else row_index

    def details(self, row: TreeRow) -> RowDetails:
        """What a row draws, read on first use."""
        found = self._details.get(row.prim)
        if found is None:
            found = self._details[row.prim] = _read_details(row.prim)
        return found

    def is_expanded(self, row: TreeRow) -> bool:
        """Whether a row's children are showing."""
        return row.prim in self.expanded

    def toggle(self, row_index: int, recursive: bool = False) -> None:
        """Expand or collapse one row; recursive applies the new state to its whole subtree."""
        self.set_expanded(row_index, self.rows[row_index].prim not in self.expanded, recursive)

    def set_expanded(self, row_index: int, expand: bool, recursive: bool = False) -> None:
        """Expand or collapse one row, or with recursive, it and everything under it."""
        row = self.rows[row_index]
        prims = list(Usd.PrimRange(row.prim, CHILD_PREDICATE)) if recursive else [row.prim]
        # Cut out whatever shows under the row now, then splice in what shows under it after the change.
        end = self._subtree_end(row_index)
        if expand:
            self.expanded.update(prims)
        else:
            self.expanded.difference_update(prims)
        self.rows[row_index + 1 : end] = self._subtree_rows(row.prim, row.depth) if expand else []
        self.version += 1

    def reveal(self, prim: Usd.Prim) -> int:
        """Expand every ancestor of a prim so its row is visible, and return that row's position."""
        ancestors: list[Usd.Prim] = []
        parent = prim.GetParent()
        while parent and not parent.IsPseudoRoot():
            ancestors.append(parent)
            parent = parent.GetParent()
        for ancestor in reversed(ancestors):  # outermost first, so each one's row exists when it expands
            if ancestor not in self.expanded:
                self.toggle(self.position(ancestor))
        return self.position(prim)

    def position(self, prim: Usd.Prim) -> int:
        """The row index of a visible prim, or -1."""
        return next((i for i, row in enumerate(self.rows) if row.prim == prim), -1)

    def _subtree_end(self, row_index: int) -> int:
        depth = self.rows[row_index].depth
        end = row_index + 1
        while end < len(self.rows) and self.rows[end].depth > depth:
            end += 1
        return end

    def _subtree_rows(self, prim: Usd.Prim, depth: int) -> list[TreeRow]:
        """The rows that show under an expanded prim, depth first."""
        rows: list[TreeRow] = []
        stack = [(child, depth + 1) for child in reversed(self._children(prim))]
        while stack:
            child, child_depth = stack.pop()
            rows.append(TreeRow(child, child_depth))
            if self.expanded and child in self.expanded:
                stack.extend((c, child_depth + 1) for c in reversed(self._children(child)))
        return rows

    def _children(self, prim: Usd.Prim) -> list[Usd.Prim]:
        children = prim.GetFilteredChildren(CHILD_PREDICATE)
        result = self.search_result
        # Under a filter, a prim that only holds matches shows just the children that lead to them. A match, and
        # anything reached by expanding below one (a prim the search didn't show), shows all its children.
        if result is None:
            return children
        if not prim.IsPseudoRoot() and (prim in result.matching_prims or prim not in result.visible_prims):
            return children
        return [child for child in children if child in result.visible_prims]


def has_children(prim: Usd.Prim) -> bool:
    """Whether a prim has any child, without listing them all (a list of names costs the size of the group)."""
    descendants = iter(Usd.PrimRange(prim, CHILD_PREDICATE))
    next(descendants)  # the prim itself
    return next(descendants, None) is not None


def _read_details(prim: Usd.Prim) -> RowDetails:
    return RowDetails(
        name=prim.GetName(),
        type_name=str(prim.GetTypeName()),
        has_children=has_children(prim),
        is_active=prim.IsActive(),
        specifier=prim.GetSpecifier(),
        has_payload=prim.HasPayload(),
        has_references=prim.HasAuthoredReferences(),
        is_instance=prim.IsInstance(),
        is_instance_proxy=prim.IsInstanceProxy(),
        has_variants=bool(prim.GetVariantSets().GetNames()),
    )


def synthetic_stage(fanout: int, depth: int, wide: int = 0) -> Usd.Stage:
    """Make an in-memory stage of nested Xforms, fanout children per level, plus one group of wide leaf prims."""
    stage = Usd.Stage.CreateInMemory()
    layer = stage.GetRootLayer()
    with Sdf.ChangeBlock():
        root = Sdf.CreatePrimInLayer(layer, "/World")
        root.specifier = Sdf.SpecifierDef
        root.typeName = "Xform"
        frontier = [root.path]
        for level in range(depth):
            next_frontier = []
            for parent in frontier:
                for i in range(fanout):
                    spec = Sdf.CreatePrimInLayer(layer, parent.AppendChild(f"g{level}_{i}"))
                    spec.specifier = Sdf.SpecifierDef
                    spec.typeName = "Xform" if level < depth - 1 else "Mesh"
                    next_frontier.append(spec.path)
            frontier = next_frontier
        if wide:
            group = Sdf.CreatePrimInLayer(layer, "/World/Wide")
            group.specifier = Sdf.SpecifierDef
            group.typeName = "Scope"
            for i in range(wide):
                spec = Sdf.CreatePrimInLayer(layer, group.path.AppendChild(f"leaf_{i}"))
                spec.specifier = Sdf.SpecifierDef
                spec.typeName = "Mesh"
    return stage
