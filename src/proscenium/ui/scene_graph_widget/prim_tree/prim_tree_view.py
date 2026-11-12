"""One prim tree as a widget shows it: its tree, selected prim, search, and the stage changes it follows.

Everything a widget does to a tree goes through here, so a widget only draws and forwards input. Stage changes
arrive as `Usd.Notice.ObjectsChanged` while the stage is being edited, when the tree can't be read safely, so the
notice only marks the view changed and tells its owner, which calls `apply_pending_changes` once the edit is over.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pxr import Sdf, Tf, Usd

from . import prim_search
from .prim_tree import PrimTree

if TYPE_CHECKING:
    from collections.abc import Callable

MATCH_LIMIT = 10_000  # matches; a search stops at this many


class StepDirection(enum.Enum):
    """Which way a key moves through the tree."""

    INTO = "into"  # Right: expand the row, or step into its first child
    OUT_OF = "out of"  # Left: collapse the row, or step out to its parent


class PendingChange(enum.IntEnum):
    """What a view must read again before it next draws, ordered so the larger includes the smaller."""

    NONE = 0
    PROPERTIES = 1  # a property was added or removed: no row changes, only what a prim's details panel counts
    DETAILS = 2  # a prim's metadata changed: the rows stay, their details are read again
    HIERARCHY = 3  # prims were added, removed, or recomposed: the rows are rebuilt


@dataclass(frozen=True, slots=True)
class SearchStatus:
    """What the last search found, or why it couldn't run."""

    text: str = ""
    is_error: bool = False


class PrimTreeView:
    """A tree, the prim selected in it, its search, and the changes to its stage it hasn't read yet."""

    tree: PrimTree | None
    selected_path: Sdf.Path | None  # a prim on the stage, whether or not its row is visible now
    query: prim_search.SearchQuery  # the query applied to the tree
    search_status: SearchStatus
    pending_change: PendingChange
    _on_stage_changed: Callable[[], None]
    _listener: Tf.Notice.Listener | None  # revoked when the stage changes or the view closes

    def __init__(self, on_stage_changed: Callable[[], None] | None = None) -> None:
        """on_stage_changed is called, during the edit, the first time the stage changes after a pending read."""
        self.tree = None
        self.selected_path = None
        self.query = prim_search.SearchQuery()
        self.search_status = SearchStatus()
        self.pending_change = PendingChange.NONE
        self._on_stage_changed = on_stage_changed or (lambda: None)
        self._listener = None

    def set_stage(self, stage: Usd.Stage | None) -> None:
        """Show a stage, or none; showing the stage already shown keeps its expansion and selection."""
        if stage is not None and self.tree is not None and self.tree.is_on_stage(stage):
            return
        self.close()
        if stage is None:
            return
        self.tree = PrimTree(stage)
        self._listener = Tf.Notice.Register(Usd.Notice.ObjectsChanged, self._stage_changed, stage)
        self.apply_query()  # a query set before the stage was shown applies to it

    def close(self) -> None:
        """Stop showing a stage and following its changes."""
        if self._listener is not None:
            self._listener.Revoke()
            self._listener = None
        self.tree = None
        self.selected_path = None
        self.search_status = SearchStatus()
        self.pending_change = PendingChange.NONE

    def live_tree(self) -> PrimTree | None:
        """The tree, if its stage is still alive."""
        return None if self.tree is None or self.tree.is_expired() else self.tree

    def active_row_index(self) -> int | None:
        """The selected prim's row, if it has one."""
        tree = self.live_tree()
        return None if tree is None or self.selected_path is None else tree.row_index(self.selected_path)

    def select_row(self, row_index: int | None) -> None:
        """Select the prim of a row, or nothing."""
        tree = self.live_tree()
        if tree is None or row_index is None or not 0 <= row_index < len(tree.rows):
            self.selected_path = None
        else:
            self.selected_path = tree.rows[row_index].path

    def select_path(self, path: Sdf.Path) -> int | None:
        """Select a prim, revealing its row; returns the row, or None if a search hides it.

        A path the stage has no prim at selects nothing.
        """
        tree = self.live_tree()
        if tree is None or not tree.has_prim(path):
            self.selected_path = None
            return None
        self.selected_path = path
        return tree.reveal(path)

    def toggle_row(self, row_index: int, recursive: bool = False) -> None:
        """Expand or collapse a row, keeping the selection."""
        tree = self.live_tree()
        if tree is not None and 0 <= row_index < len(tree.rows):
            tree.toggle(row_index, recursive)

    def step(self, direction: StepDirection, recursive: bool) -> int | None:
        """Move through the tree from the keys, from the selected row (or the first), and select where it lands."""
        tree = self.live_tree()
        if tree is None or not tree.rows:
            return None
        row_index = self.active_row_index() or 0
        if recursive:
            tree.set_expanded(row_index, direction is StepDirection.INTO, recursive=True)
            target_index = row_index
        elif direction is StepDirection.INTO:
            target_index = tree.expand_or_enter_row(row_index)
        else:
            target_index = tree.collapse_or_select_parent(row_index)
        self.selected_path = tree.rows[target_index].path
        return target_index

    def set_query(self, query: prim_search.SearchQuery) -> None:
        """Search for a query, or with an empty one, clear the search."""
        self.query = query
        self.apply_query()

    def apply_query(self) -> None:
        """Run the query and filter the tree by it; clearing it reveals the selected prim.

        It searches the whole stage, or with shown_rows_only, the rows the tree shows without its filter.
        """
        tree = self.live_tree()
        if tree is None:
            return
        stage = tree.stage()
        if self.query.is_empty() or stage is None:
            tree.set_search(None)
            self.search_status = SearchStatus()
            if self.selected_path is not None:
                tree.reveal(self.selected_path)
            return
        start = time.perf_counter()
        try:
            candidate_prims = tree.unfiltered_prims() if self.query.shown_rows_only else None
            result = prim_search.search(stage, self.query, MATCH_LIMIT, candidate_prims)
        except prim_search.SearchError as error:
            self.search_status = SearchStatus(f"Search: {error}", is_error=True)
            return
        elapsed_ms = (time.perf_counter() - start) * 1000
        tree.set_search(result)
        first = f"first {MATCH_LIMIT:,} " if result.is_truncated else ""
        scope = " in shown rows" if self.query.shown_rows_only else ""
        matches = f"{first}{len(result.matching_paths):,} matches{scope}"
        self.search_status = SearchStatus(f"{matches} in {elapsed_ms:.0f} ms")

    def apply_pending_changes(self) -> bool:
        """Read the stage changes the notices marked; returns whether there were any."""
        pending_change, self.pending_change = self.pending_change, PendingChange.NONE
        tree = self.live_tree()
        if tree is None or pending_change is PendingChange.NONE:
            return False
        if pending_change is PendingChange.HIERARCHY:
            tree.refresh()
            # A selected prim that's gone is deselected; one that's only hidden, by a collapse or a search, stays.
            if self.selected_path is not None and not tree.has_prim(self.selected_path):
                self.selected_path = None
            if not self.query.is_empty():
                self.apply_query()  # the old result's paths may be gone, and new prims may match
        elif pending_change is PendingChange.DETAILS:
            tree.forget_details()
        else:
            tree.forget_prim_details()
        return True

    def _stage_changed(self, notice: Usd.Notice.ObjectsChanged, _sender: Usd.Stage) -> None:
        # Adding or removing a property resyncs its path, not its prim's, and changes no row.
        resynced_paths = notice.GetResyncedPaths()
        if any(_is_prim_or_root(path) for path in resynced_paths):
            change = PendingChange.HIERARCHY
        elif any(_is_prim_or_root(path) for path in notice.GetChangedInfoOnlyPaths()):
            change = PendingChange.DETAILS
        elif resynced_paths:
            change = PendingChange.PROPERTIES
        else:
            return  # only property values changed, which nothing shows
        was_pending = self.pending_change is not PendingChange.NONE
        self.pending_change = max(self.pending_change, change)
        if not was_pending:
            self._on_stage_changed()


def _is_prim_or_root(path: Sdf.Path) -> bool:
    return path.IsPrimPath() or path.IsAbsoluteRootPath()
