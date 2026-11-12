"""Which partitions a synchronization prepares, and which published entries they replace (incremental.md).

A refresh compares its plan with the plan of the generation the destination shows, held since this session published
it (binding.runtime.held_plans), through the core's plan diff (change-matrix.md "Actions"), and prepares only the
partitions of the copies the diff builds or changes. Without a held plan, as on a first synchronization, after
reopening, or after an undo past the held plans, and on a requested full rebuild, every partition is prepared
(AFF-04).

Provisional (M7 plan, C6a): every kept copy the diff changes is rebuilt, until local updates change one in place
(C6b); so is a kept copy with cached keys, which synchronizing again removes (C6c), and one whose published resources
are incomplete, as when the user deleted its object. A copy's published entries are those whose source entity is its
source path: an action's with its object's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..binding.persistence import manifests
from ..core import _core

if TYPE_CHECKING:
    from collections.abc import Buffer


@dataclass(frozen=True)
class PartitionReplacement:
    """The new plan's copies whose partitions a synchronization prepares, and the published entries it replaces."""

    prepared_copy_indices: tuple[int, ...]  # in plan order
    # The published entries of the partitions prepared anew and of the copies the plan no longer has, by entry key.
    replaced_entry_keys: frozenset[str]


def partitions_to_replace(
    shown: _core.Plan | None, plan: _core.Plan, published: manifests.Manifest
) -> PartitionReplacement:
    """What a synchronization of plan replaces: every partition without shown, else what differs from it.

    shown is the held plan of the generation published displays, or None, as for a full rebuild (AFF-04).
    """
    return every_partition(plan, published) if shown is None else changed_partitions(shown, plan, published)


def every_partition(plan: _core.Plan, published: manifests.Manifest) -> PartitionReplacement:
    """Every partition prepared, replacing every published entry: a full rebuild."""
    return PartitionReplacement(tuple(range(plan.copy_count)), frozenset(published.entries))


def changed_partitions(previous: _core.Plan, plan: _core.Plan, published: manifests.Manifest) -> PartitionReplacement:
    """The partitions of plan's copies that differ from previous's, the plan published is the display of."""
    diff = _core.diff_plans(previous, plan)
    matched = _indices(diff.previous_copy_indices)
    changed = {
        copy
        for buffer in (
            diff.rebuilt_copy_indices,
            diff.moved_copy_indices,
            diff.bounds_changed_copy_indices,
            diff.participation_changed_copy_indices,
        )
        for copy in _indices(buffer)
    }
    keys_by_source: dict[str, set[str]] = {}
    keyed: set[str] = set()  # the sources of copies with cached keys
    incomplete: set[str] = set()  # the sources of copies with a published resource gone
    for entry_key, entry in published.entries.items():
        if (identity := entry.identity) is None:
            continue
        keys_by_source.setdefault(identity.entity, set()).add(entry_key)
        if identity.role is manifests.RepresentationRole.ACTION:
            keyed.add(identity.entity)
        if entry.datablock is None:
            incomplete.add(identity.entity)
    sources = [entry.source_path for entry in plan.correspondence]
    previous_sources = [entry.source_path for entry in previous.correspondence]
    prepared = tuple(
        copy
        for copy, old in enumerate(matched)
        if old < 0 or copy in changed or sources[copy] in keyed | incomplete or sources[copy] not in keys_by_source
    )
    replaced = {key for copy in prepared for key in keys_by_source.get(sources[copy], ())}
    for old in _indices(diff.removed_previous_copy_indices):
        replaced |= keys_by_source.get(previous_sources[old], set())
    return PartitionReplacement(prepared, frozenset(replaced))


def _indices(buffer: Buffer) -> list[int]:
    with memoryview(buffer) as view:  # released before returning (SNAP-13)
        return view.tolist()
