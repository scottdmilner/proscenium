"""One property list as a widget shows it: the prim it shows, its selected row, search, time code, and stage changes.

Everything a widget does to a list goes through here, so a widget only draws and forwards input. A host shows a stage
and then a prim on it, such as the prim a scene graph selects. The selection and the expansion are kept by property
name, so showing another prim keeps the same property selected, and the same relationships expanded, where it has
them: one property can be compared across prims.

Stage changes arrive as `Usd.Notice.ObjectsChanged` while the stage is being edited, when the list can't be read
safely, so the notice only marks the view changed and tells its owner, which calls `apply_pending_changes` once the
edit is over.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pxr import Sdf, Tf, Usd

from ...widget_model import text_matching
from ...widget_model.list_steps import StepDirection
from . import property_search
from .property_list import PropertyList, PropertyRow

if TYPE_CHECKING:
    from collections.abc import Callable


class PropertyListView:
    """A prim's property list, the row selected in it, its search, and the changes to its stage it hasn't read yet."""

    property_list: PropertyList | None  # None while no prim is shown, or the stage has none at prim_path
    prim_path: Sdf.Path | None  # the prim the host shows, whether or not the stage has one there now
    selected_row: PropertyRow | None  # by name, so it carries over to the next prim shown
    query: property_search.SearchQuery  # the query applied to the list
    search_error: str  # why the query couldn't be applied, or empty
    time_code: Usd.TimeCode
    has_pending_change: bool  # whether the stage changed in a way the list shows, and the list wasn't read since
    expanded_names: set[str]  # the properties whose targets show, on whichever prim is shown
    _pseudo_root: Usd.Prim | None  # the stage, held as its pseudo-root so it isn't kept alive
    _on_stage_changed: Callable[[], None]
    _listener: Tf.Notice.Listener | None  # revoked when the stage changes or the view closes

    def __init__(self, on_stage_changed: Callable[[], None] | None = None) -> None:
        """on_stage_changed is called, during the edit, the first time the stage changes after a pending read."""
        self.property_list = None
        self.prim_path = None
        self.selected_row = None
        self.query = property_search.SearchQuery()
        self.search_error = ""
        self.time_code = Usd.TimeCode.Default()
        self.has_pending_change = False
        self.expanded_names = set()
        self._pseudo_root = None
        self._on_stage_changed = on_stage_changed or (lambda: None)
        self._listener = None

    def set_stage(self, stage: Usd.Stage | None) -> None:
        """Show a stage, or none, with no prim until show_prim; the stage already shown keeps its prim."""
        if stage is not None and self._is_on_stage(stage):
            return
        self.close()
        if stage is not None:
            self._pseudo_root = stage.GetPseudoRoot()
            self._listener = Tf.Notice.Register(Usd.Notice.ObjectsChanged, self._stage_changed, stage)

    def show_prim(self, path: Sdf.Path | None) -> None:
        """Show a prim's properties, or none; its selected row carries over where the prim has that property."""
        self.apply_pending_changes()
        self.prim_path = path
        self._rebuild_list()

    def close(self) -> None:
        """Stop showing a stage and following its changes."""
        if self._listener is not None:
            self._listener.Revoke()
            self._listener = None
        self._pseudo_root = None
        self.prim_path = None
        self.property_list = None
        self.has_pending_change = False

    def stage(self) -> Usd.Stage | None:
        """The stage shown, or None: none was given, or it has been released."""
        return self._pseudo_root.GetStage() if self._pseudo_root is not None and self._pseudo_root.IsValid() else None

    def is_stage_expired(self) -> bool:
        """Whether a stage was given and has since been released."""
        return self._pseudo_root is not None and not self._pseudo_root.IsValid()

    def live_list(self) -> PropertyList | None:
        """The list, if its stage is alive and its prim hasn't been removed or recomposed since it was read."""
        property_list = self.property_list
        return None if property_list is None or property_list.is_expired() else property_list

    @property
    def selected_path(self) -> Sdf.Path | None:
        """The selected property's path on the shown prim, or None; a target's row selects its property."""
        if self.selected_row is None or self.live_list() is None or self.prim_path is None:
            return None
        return self.prim_path.AppendProperty(self.selected_row.name)

    def active_row_index(self) -> int | None:
        """The selected row's index, if it's visible."""
        property_list = self.live_list()
        return (
            None if property_list is None or self.selected_row is None else property_list.row_index(self.selected_row)
        )

    def select_row(self, row_index: int | None) -> None:
        """Select a row drawn before any pending changes, or nothing, as when the row is gone since."""
        self.selected_row = self._row_after_pending_changes(row_index)

    def select_property(self, name: str | None) -> None:
        """Select a property by name, or nothing; a name the prim has no property of selects nothing."""
        self.apply_pending_changes()
        property_list = self.live_list()
        has_property = name is not None and property_list is not None and property_list.details(name) is not None
        self.selected_row = PropertyRow(name) if has_property and name is not None else None

    def toggle_row(self, row_index: int, every_property: bool = False) -> None:
        """Show or hide the targets of a row's property, as drawn before any pending changes, keeping the selection.

        With every_property, every property's targets show or hide with it.
        """
        row = self._row_after_pending_changes(row_index)
        property_list = self.live_list()
        if row is None or property_list is None:
            return
        current_row_index = property_list.row_index(row)
        if current_row_index is not None:
            property_list.toggle(current_row_index, every_property)
        self._select_property_of_hidden_target(property_list)

    def step(self, direction: StepDirection, every_property: bool) -> None:
        """Move through the list from the keys, from the selected row (or the first), and select where it lands.

        Right shows a property's targets, or steps into its first; Left hides them, or steps out of a target to its
        property. With every_property (Shift), every property's targets show or hide, and the selection stays.
        """
        self.apply_pending_changes()  # the selected row is found by its name, in the rows after them
        property_list = self.live_list()
        if property_list is None or not property_list.rows:
            return
        row_index = self.active_row_index() or 0
        row = property_list.rows[row_index]
        self.selected_row = row
        if every_property:
            property_list.set_all_expanded(direction is StepDirection.INTO)
            self._select_property_of_hidden_target(property_list)
            return
        details = property_list.row_details(row)
        has_targets = details is not None and details.has_targets
        if direction is StepDirection.OUT_OF:
            if row.is_target:
                self.selected_row = PropertyRow(row.name)
            elif has_targets and property_list.is_expanded(row.name):
                property_list.set_expanded(row.name, expand=False)
        elif has_targets and not row.is_target:
            if property_list.is_expanded(row.name):
                self.selected_row = property_list.rows[row_index + 1]  # its first target's
            else:
                property_list.set_expanded(row.name, expand=True)

    def _select_property_of_hidden_target(self, property_list: PropertyList) -> None:
        """Select the property of a selected target whose row is hidden, as when its property collapses."""
        row = self.selected_row
        if row is not None and row.is_target and property_list.row_index(row) is None:
            self.selected_row = PropertyRow(row.name)

    def set_query(self, query: property_search.SearchQuery) -> None:
        """Filter the properties by a query, or with an empty one, show them all."""
        self.query = query
        self._rebuild_list()

    def set_time_code(self, time_code: Usd.TimeCode) -> None:
        """Show the values at another time code."""
        self.time_code = time_code
        if self.property_list is not None:
            self.property_list.set_time_code(time_code)

    def apply_pending_changes(self) -> bool:
        """Read the stage changes the notices marked; returns whether there were any.

        A released stage sends no notice, so this is also where a selection on it is dropped, as a change.
        """
        has_pending_change, self.has_pending_change = self.has_pending_change, False
        if self.is_stage_expired() and self.property_list is not None:
            self.property_list = None
            return True
        if has_pending_change:
            self._rebuild_list()  # a prim's properties are few, so they're read again whatever changed
        return has_pending_change

    def _is_on_stage(self, stage: Usd.Stage) -> bool:
        return (
            self._pseudo_root is not None and self._pseudo_root.IsValid() and self._pseudo_root == stage.GetPseudoRoot()
        )

    def _rebuild_list(self) -> None:
        """Read the shown prim's properties again, and keep the selection where the prim still has it."""
        stage = self.stage()
        prim = stage.GetPrimAtPath(self.prim_path) if stage is not None and self.prim_path is not None else None
        if prim is None or not prim or prim.IsPseudoRoot():
            self.property_list = None
            return
        try:
            shows_property = property_search.matcher(self.query)
            self.search_error = ""
        except text_matching.InvalidPatternError as error:
            shows_property = None  # every property shows while the pattern can't be read
            self.search_error = f"Search: {error}"
        self.property_list = PropertyList(prim, self.time_code, self.expanded_names, shows_property)
        self._keep_selection(self.property_list)

    def _keep_selection(self, property_list: PropertyList) -> None:
        """Keep the selected row on a new list: its target's row if it shows, else its property's, else nothing."""
        row = self.selected_row
        if row is None:
            return
        details = property_list.details(row.name)
        if details is None:
            self.selected_row = None
        elif row.target_path is not None and property_list.row_index(row) is None:
            self.selected_row = PropertyRow(row.name)

    def _row_after_pending_changes(self, row_index: int | None) -> PropertyRow | None:
        """A row drawn before the pending changes, if it's still there once they're read; None if it isn't.

        Input names a row by its index in the rows last drawn, which a change pending since then makes stale: the
        same index may be another property's after the rows are read again.
        """
        property_list = self.live_list()
        if property_list is None or row_index is None or not 0 <= row_index < len(property_list.rows):
            self.apply_pending_changes()
            return None
        row = property_list.rows[row_index]
        self.apply_pending_changes()
        property_list = self.live_list()
        return row if property_list is not None and property_list.row_index(row) is not None else None

    def _stage_changed(self, notice: Usd.Notice.ObjectsChanged, _sender: Usd.Stage) -> None:
        # Any resync may have recomposed the prim, added or removed a property, or removed a target's prim; a field of
        # the shown prim's properties, such as a value or a relationship's targets, changes their rows too. Another
        # prim's fields change nothing shown.
        is_shown = notice.GetResyncedPaths() or any(
            self._is_shown_property_or_prim(path) for path in notice.GetChangedInfoOnlyPaths()
        )
        if not is_shown or self.has_pending_change:
            return
        self.has_pending_change = True
        self._on_stage_changed()

    def _is_shown_property_or_prim(self, path: Sdf.Path) -> bool:
        return self.prim_path is not None and path.GetPrimPath() == self.prim_path
