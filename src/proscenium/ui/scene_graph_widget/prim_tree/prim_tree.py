"""A stage's prim hierarchy as the flat list of rows a tree widget shows.

Rows are spliced in on expand and cut out on collapse, so each costs the rows it adds or removes, and a row holds
only its prim and depth. What a row draws (`RowDetails`) is read from the prim when the row is first drawn, so a
widget pays for the rows on screen, not the rows in the list.

A tree holds its stage's prims and never the stage, so it never keeps a stage alive: once the stage's last owner
releases it, the tree is expired. Expansion and details are kept by path, so they survive the stage recomposing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pxr import Sdf, Usd

from .prim_children import CHILD_PREDICATE, has_children

if TYPE_CHECKING:
    from .prim_search import SearchResult


@dataclass(frozen=True, slots=True)
class TreeRow:
    """One visible prim and how deep it sits; top-level prims are at depth 0."""

    prim: Usd.Prim
    depth: int

    @property
    def path(self) -> Sdf.Path:
        """The row's prim path."""
        return self.prim.GetPath()


@dataclass(frozen=True, slots=True)
class RowDetails:
    """What a row draws, read from its prim."""

    name: str
    display_name: str  # the prim's displayName metadata, or empty
    type_name: str
    has_children: bool
    is_active: bool
    specifier: Sdf.Specifier
    has_payload: bool
    has_references: bool
    is_instance: bool
    is_instance_proxy: bool
    has_variants: bool

    @property
    def is_class(self) -> bool:
        """Whether the prim is a class: its strongest defining opinion is a class, not a def."""
        return self.specifier == Sdf.SpecifierClass

    @property
    def is_orphaned_over(self) -> bool:
        """Whether nothing defines the prim: a composed prim is an over only when every opinion on it is one."""
        return self.specifier == Sdf.SpecifierOver


class PrimTree:
    """The expansion state of one stage's hierarchy, and the rows it makes visible."""

    rows: list[TreeRow]
    expanded_paths: set[Sdf.Path]
    version: int  # counts changes to rows, so a widget can cache what it computes from them
    search_result: SearchResult | None  # the filter, while one is set
    _pseudo_root: Usd.Prim
    _details_by_path: dict[Sdf.Path, RowDetails]
    _expanded_paths_before_search: set[Sdf.Path]  # restored when the filter clears

    def __init__(self, stage: Usd.Stage) -> None:
        self._pseudo_root = stage.GetPseudoRoot()
        self.expanded_paths = set()
        self._details_by_path = {}
        self._expanded_paths_before_search = set()
        self.version = 0
        self.search_result = None
        self.rows = self._subtree_rows(self._pseudo_root, -1)

    def is_expired(self) -> bool:
        """Whether the stage has been released, so the tree's prims can no longer be read."""
        return not self._pseudo_root.IsValid()

    def stage(self) -> Usd.Stage | None:
        """The tree's stage, or None once it has been released."""
        return None if self.is_expired() else self._pseudo_root.GetStage()

    def is_on_stage(self, stage: Usd.Stage) -> bool:
        """Whether the tree shows this stage."""
        return not self.is_expired() and self._pseudo_root == stage.GetPseudoRoot()

    def has_prim(self, path: Sdf.Path) -> bool:
        """Whether the stage has a prim at a path, so the tree can show it, whether or not its row is visible now."""
        stage = self.stage()
        return stage is not None and path.IsPrimPath() and bool(stage.GetPrimAtPath(path))

    def details(self, row: TreeRow) -> RowDetails:
        """What a row draws, read on first use."""
        path = row.path
        found = self._details_by_path.get(path)
        if found is None:
            found = self._details_by_path[path] = _read_details(row.prim)
        return found

    def is_expanded(self, row: TreeRow) -> bool:
        """Whether a row's children are showing."""
        return row.path in self.expanded_paths

    def is_match(self, row: TreeRow) -> bool:
        """Whether a row shows because it matched the filter (rather than holding a match), or no filter is set."""
        return self.search_result is None or row.path in self.search_result.matching_paths

    def row_index(self, path: Sdf.Path) -> int | None:
        """The index of a visible prim's row, or None if it has none."""
        return next((i for i, row in enumerate(self.rows) if row.path == path), None)

    def toggle(self, row_index: int, recursive: bool = False) -> None:
        """Expand or collapse one row; recursive applies the new state to its whole subtree."""
        self.set_expanded(row_index, not self.is_expanded(self.rows[row_index]), recursive)

    def set_expanded(self, row_index: int, expand: bool, recursive: bool = False) -> None:
        """Expand or collapse one row, or with recursive, it and everything under it."""
        row = self.rows[row_index]
        prims = Usd.PrimRange(row.prim, CHILD_PREDICATE) if recursive else (row.prim,)
        paths = {prim.GetPath() for prim in prims}
        # Cut out whatever shows under the row now, then splice in what shows under it after the change.
        end = self._subtree_end(row_index)
        if expand:
            self.expanded_paths.update(paths)
        else:
            self.expanded_paths.difference_update(paths)
        self.rows[row_index + 1 : end] = self._subtree_rows(row.prim, row.depth) if expand else []
        self.version += 1

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
        parent_index = row_index - 1
        while parent_index >= 0 and self.rows[parent_index].depth >= row.depth:
            parent_index -= 1
        return parent_index if parent_index >= 0 else row_index

    def reveal(self, path: Sdf.Path) -> int | None:
        """Expand every ancestor of a prim so its row is visible, and return that row's index.

        None if the prim has no row even then: it doesn't exist, or a search filter hides it.
        """
        for ancestor_path in path.GetPrefixes()[:-1]:  # outermost first, so each one's row exists when it expands
            if ancestor_path in self.expanded_paths:
                continue
            ancestor_index = self.row_index(ancestor_path)
            if ancestor_index is None:
                return None
            self.set_expanded(ancestor_index, True)
        return self.row_index(path)

    def set_search(self, result: SearchResult | None) -> None:
        """Show only a search's matches and their ancestors, expanded to reach them; None shows everything again.

        A match's own children all show when it is expanded, so a match can be explored from. Clearing the
        filter restores the expansion from before it.
        """
        if result is not None:
            if self.search_result is None:
                self._expanded_paths_before_search = set(self.expanded_paths)
            self.expanded_paths = {path.GetParentPath() for path in result.visible_paths}
        elif self.search_result is not None:
            self.expanded_paths = self._expanded_paths_before_search
        self.search_result = result
        self._rebuild_rows()

    def refresh(self) -> None:
        """Read the stage again after it changed: every row's details, and the rows of what is expanded.

        Expanded paths whose prims are gone are dropped. A search result isn't rerun here; whoever set it does.
        """
        stage = self.stage()
        if stage is None:
            return
        self._details_by_path.clear()
        self.expanded_paths = {path for path in self.expanded_paths if stage.GetPrimAtPath(path)}
        self._rebuild_rows()

    def forget_details(self) -> None:
        """Read every row's details again when it next draws, after the stage's metadata changed."""
        self._details_by_path.clear()
        self.version += 1

    def _rebuild_rows(self) -> None:
        self.rows = self._subtree_rows(self._pseudo_root, -1)
        self.version += 1

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
            if child.GetPath() in self.expanded_paths:
                stack.extend((c, child_depth + 1) for c in reversed(self._children(child)))
        return rows

    def _children(self, prim: Usd.Prim) -> list[Usd.Prim]:
        children = prim.GetFilteredChildren(CHILD_PREDICATE)
        result = self.search_result
        # Under a filter, a prim that only holds matches shows just the children that lead to them. A match, and
        # anything reached by expanding below one (a prim the search didn't show), shows all its children.
        if result is None:
            return children
        path = prim.GetPath()
        if not prim.IsPseudoRoot() and (path in result.matching_paths or path not in result.visible_paths):
            return children
        return [child for child in children if child.GetPath() in result.visible_paths]


def _read_details(prim: Usd.Prim) -> RowDetails:
    return RowDetails(
        name=prim.GetName(),
        display_name=prim.GetDisplayName(),
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
