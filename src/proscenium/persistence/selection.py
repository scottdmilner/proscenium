"""The persistent selection: a scene's stored source selection (interaction-contract.md#persistent-selection).

An ordered set of (binding identifier, source-entity identifier) entries plus an optional active
entry, stored as a record on the scene. It may hold entries from several bindings, and stores
targets, not their expanded members. An entry whose binding is gone, or whose path the current
generation doesn't display, stays stored; resolving it against a published generation, and
mirroring it into Blender's selection, are M7's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from . import records
from .records import Schema

if TYPE_CHECKING:
    import bpy

    from .records import Loaded, Refused

SELECTION_KEY = "selection"


class SelectionEntry(NamedTuple):
    binding_id: str
    path: str  # a source-entity identifier: make it with proscenium.core.source_entities.identifier


@dataclass(frozen=True)
class PersistentSelection:
    entries: tuple[SelectionEntry, ...]  # in order; a set, so no entry twice
    active: SelectionEntry | None  # one of the entries, or none

    def __post_init__(self) -> None:
        # A stored selection's entries are lists of two strings; make them entries again.
        entries = tuple(SelectionEntry(*entry) for entry in self.entries)
        active = None if self.active is None else SelectionEntry(*self.active)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "active", active)
        # Paths are checked as identifiers where they're made and where they're resolved, not on each
        # read: a damaged one then fails to resolve and is reported unresolved, as for a path that names nothing.
        if not all(type(binding_id) is str and type(path) is str for binding_id, path in entries):
            raise TypeError("an entry is a binding identifier and a path, both strings")
        if len(set(entries)) != len(entries):
            raise ValueError("an entry appears twice")
        if active is not None and active not in entries:
            raise ValueError("the active entry is not one of the entries")


SELECTION = Schema("selection", version=1, record=PersistentSelection)


def read_selection(scene: bpy.types.Scene) -> Loaded[PersistentSelection] | Refused | None:
    return records.read(scene, SELECTION_KEY, SELECTION)


def write_selection(scene: bpy.types.Scene, selection: PersistentSelection) -> None:
    """Raises RecordRefused, changing nothing, over a stored selection that can't be read."""
    records.write(scene, SELECTION_KEY, SELECTION, selection)
