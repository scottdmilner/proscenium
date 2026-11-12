"""A stage's prim hierarchy as the flat list of rows a tree widget shows.

Rows are spliced in on expand and cut out on collapse, so each costs the rows it adds or removes, and a row holds
only its prim and depth. What a row draws (`RowDetails`) is read from the prim when the row is first drawn, so a
widget pays for the rows on screen, not the rows in the list. What only one prim's details or tooltips show at a time
(`PrimDetails`) is read when first asked for, so a panel redrawing it doesn't read it again.

These two records are all the tree reads of a prim's details: what the tree says about a prim (prim_descriptions) is
worded from them alone.

A tree holds its stage's prims and never the stage, so it never keeps a stage alive: once the stage's last owner
releases it, the tree is expired. Expansion and details are kept by path, so they survive the stage recomposing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pxr import Kind, Sdf, Usd

from .prim_children import CHILD_PREDICATE, has_children

if TYPE_CHECKING:
    from collections.abc import Callable

    from .prim_search import SearchResult


@dataclass(frozen=True, slots=True)
class TreeRow:
    """One visible prim and how deep it sits; top-level prims are at depth 0."""

    prim: Usd.Prim
    path: Sdf.Path  # the prim's, kept so the rows can be searched and drawn without asking USD for it
    depth: int


@dataclass(frozen=True, slots=True)
class RowDetails:
    """What a row draws and its tooltip says, read from its prim."""

    path: Sdf.Path
    name: str
    display_name: str  # the prim's displayName metadata, or empty
    type_name: str
    model_kind: str  # the prim's kind metadata, or empty
    is_invalid_model: bool  # see _is_invalid_model
    has_children: bool
    is_active: bool
    specifier: Sdf.Specifier
    # The composition arcs authored on the prim, as its badges show them.
    has_inherits: bool
    has_variants: bool
    has_variant_selection: bool  # whether any of its variant sets has a variant selected
    has_references: bool
    has_payload: bool
    is_loaded: bool  # false only under an unloaded payload, its own or an ancestor's
    has_specializes: bool
    is_instance: bool
    is_instance_proxy: bool

    @property
    def is_class(self) -> bool:
        """Whether the prim is a class: its strongest defining opinion is a class, not a def."""
        return self.specifier == Sdf.SpecifierClass

    @property
    def is_orphaned_over(self) -> bool:
        """Whether nothing defines the prim: a composed prim is an over only when every opinion on it is one."""
        return self.specifier == Sdf.SpecifierOver


@dataclass(frozen=True, slots=True)
class PrimDetails:
    """What the details panel and row tooltip say about one prim beyond its `RowDetails`, read when asked for."""

    inherit_paths: tuple[str, ...]
    reference_targets: tuple[str, ...]  # each as @asset@prim, or a bare prim path for an internal reference
    payload_targets: tuple[str, ...]
    specialize_paths: tuple[str, ...]
    variant_selections: tuple[tuple[str, str], ...]  # (variant set name, selection), the selection empty if unset
    prototype_path: Sdf.Path | None  # an instance's prototype
    prim_in_prototype_path: Sdf.Path | None  # an instance proxy's prim in its prototype
    authored_attribute_count: int
    child_count: int  # instance proxies included


class PrimTree:
    """The expansion state of one stage's hierarchy, and the rows it makes visible."""

    rows: list[TreeRow]
    expanded_paths: set[Sdf.Path]
    version: int  # counts changes to rows, so a widget can cache what it computes from them
    search_result: SearchResult | None  # the filter, while one is set
    _pseudo_root: Usd.Prim
    _details_by_path: dict[Sdf.Path, RowDetails]
    _prim_details_by_path: dict[Sdf.Path, PrimDetails]
    _expanded_paths_before_search: set[Sdf.Path]  # restored when the filter clears

    def __init__(self, stage: Usd.Stage) -> None:
        self._pseudo_root = stage.GetPseudoRoot()
        self.expanded_paths = set()
        self._details_by_path = {}
        self._prim_details_by_path = {}
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
        return self._prim_at(path) is not None

    def details(self, row: TreeRow) -> RowDetails:
        """What a row draws, read on first use."""
        found = self._details_by_path.get(row.path)
        if found is None:
            found = self._details_by_path[row.path] = _read_details(row.prim)
        return found

    def details_at(self, path: Sdf.Path) -> RowDetails | None:
        """A prim's `RowDetails`, whether or not its row is visible now; None if the stage has no prim there."""
        return self._cached_at(path, self._details_by_path, _read_details)

    def prim_details(self, path: Sdf.Path) -> PrimDetails | None:
        """A prim's `PrimDetails`, read on first use; None if the stage has no prim there.

        A details panel asks on every redraw, so this is cached as `RowDetails` is, and read again after the same
        changes, and after a property is added or removed (`forget_prim_details`).
        """
        return self._cached_at(path, self._prim_details_by_path, _read_prim_details)

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
        # Cut out whatever shows under the row now, then splice in what shows under it after the change.
        end = self._subtree_end(row_index)
        if expand and recursive:
            self.expanded_paths.update(prim.GetPath() for prim in Usd.PrimRange(row.prim, CHILD_PREDICATE))
        elif expand:
            self.expanded_paths.add(row.path)
        elif recursive:  # only expanded paths can be collapsed, so filter them rather than walk the subtree
            self.expanded_paths.difference_update([path for path in self.expanded_paths if path.HasPrefix(row.path)])
        else:
            self.expanded_paths.discard(row.path)
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

    def unfiltered_prims(self) -> list[Usd.Prim]:
        """The prims of the rows the tree shows without its search filter, in row order.

        Under a filter, that's by the expansion from before the search, which clearing the filter restores.
        """
        expanded_paths = self._expanded_paths_before_search if self.search_result is not None else self.expanded_paths
        prims: list[Usd.Prim] = []
        stack = list(reversed(self._pseudo_root.GetFilteredChildren(CHILD_PREDICATE)))
        while stack:
            prim = stack.pop()
            prims.append(prim)
            if prim.GetPath() in expanded_paths:
                stack.extend(reversed(prim.GetFilteredChildren(CHILD_PREDICATE)))
        return prims

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
        self._prim_details_by_path.clear()
        self.expanded_paths = {path for path in self.expanded_paths if stage.GetPrimAtPath(path)}
        self._rebuild_rows()

    def forget_details(self) -> None:
        """Read every row's details again when it next draws, after the stage's metadata changed."""
        self._details_by_path.clear()
        self._prim_details_by_path.clear()
        self.version += 1

    def forget_prim_details(self) -> None:
        """Read `PrimDetails` again when next asked for, after a property was added or removed; rows don't change."""
        self._prim_details_by_path.clear()

    def _prim_at(self, path: Sdf.Path) -> Usd.Prim | None:
        stage = self.stage()
        prim = stage.GetPrimAtPath(path) if stage is not None and path.IsPrimPath() else None
        return prim if prim else None

    def _cached_at[Details](
        self, path: Sdf.Path, cache: dict[Sdf.Path, Details], read: Callable[[Usd.Prim], Details]
    ) -> Details | None:
        """A prim's cached details, read into the cache first if they aren't there; None if there's no prim."""
        if self.is_expired():
            return None
        found = cache.get(path)
        if found is None:
            prim = self._prim_at(path)  # looked up only on a miss: a cached path had a prim at the last refresh
            if prim is None:
                return None
            found = cache[path] = read(prim)
        return found

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
            child_path = child.GetPath()
            rows.append(TreeRow(child, child_path, child_depth))
            if child_path in self.expanded_paths:
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


def _is_invalid_model(model_api: Usd.ModelAPI, model_kind: str) -> bool:
    """Whether a prim's kind is a model kind but USD doesn't count it a model, its ancestors not all being groups."""
    return bool(model_kind) and Kind.Registry.IsA(model_kind, Kind.Tokens.model) and not model_api.IsModel()


def _read_details(prim: Usd.Prim) -> RowDetails:
    model_api = Usd.ModelAPI(prim)
    model_kind = str(model_api.GetKind())
    return RowDetails(
        path=prim.GetPath(),
        name=prim.GetName(),
        display_name=prim.GetDisplayName(),
        type_name=str(prim.GetTypeName()),
        model_kind=model_kind,
        is_invalid_model=_is_invalid_model(model_api, model_kind),
        has_children=has_children(prim),
        is_active=prim.IsActive(),
        specifier=prim.GetSpecifier(),
        has_inherits=prim.HasAuthoredInherits(),
        has_variants=prim.HasVariantSets(),
        has_variant_selection=_has_variant_selection(prim),
        has_references=prim.HasAuthoredReferences(),
        has_payload=prim.HasPayload(),
        is_loaded=prim.IsLoaded(),
        has_specializes=prim.HasAuthoredSpecializes(),
        is_instance=prim.IsInstance(),
        is_instance_proxy=prim.IsInstanceProxy(),
    )


def _has_variant_selection(prim: Usd.Prim) -> bool:
    if not prim.HasVariantSets():
        return False
    variant_sets = prim.GetVariantSets()
    return any(variant_sets.GetVariantSelection(name) for name in variant_sets.GetNames())


def _arc_targets(prim: Usd.Prim, list_name: str) -> tuple[str, ...]:
    """The targets a prim's specs author for references or payloads."""
    arcs = [arc for spec in prim.GetPrimStack() for arc in getattr(spec, list_name).ApplyEditsToList([])]
    return tuple(f"@{arc.assetPath}@{arc.primPath}" if arc.assetPath else str(arc.primPath) for arc in arcs)


def _arc_paths(prim: Usd.Prim, list_name: str) -> tuple[str, ...]:
    """The prim paths a prim's specs author for inherits or specializes."""
    return tuple(str(path) for spec in prim.GetPrimStack() for path in getattr(spec, list_name).ApplyEditsToList([]))


def _read_prim_details(prim: Usd.Prim) -> PrimDetails:
    variant_sets = prim.GetVariantSets()
    return PrimDetails(
        inherit_paths=_arc_paths(prim, "inheritPathList"),
        reference_targets=_arc_targets(prim, "referenceList"),
        payload_targets=_arc_targets(prim, "payloadList"),
        specialize_paths=_arc_paths(prim, "specializesList"),
        variant_selections=tuple((name, variant_sets.GetVariantSelection(name)) for name in variant_sets.GetNames()),
        prototype_path=prim.GetPrototype().GetPath() if prim.IsInstance() else None,
        prim_in_prototype_path=prim.GetPrimInPrototype().GetPath() if prim.IsInstanceProxy() else None,
        authored_attribute_count=len(prim.GetAuthoredAttributes()),
        child_count=len(prim.GetFilteredChildren(CHILD_PREDICATE)),
    )
