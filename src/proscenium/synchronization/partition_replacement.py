"""Which partitions a synchronization prepares, which copies it updates in place, and which entries it replaces.

incremental.md "Affected Content".

A refresh compares its plan with the plan of the generation the destination shows, held since this session published
it (binding.runtime.held_plans), through the core's plan diff (change-matrix.md "Actions"). It prepares the partitions
of the copies the diff builds, and of the kept copies whose partitions hold other resources; a kept copy that only
moved, changed its bounds, changed its participation, or holds a cached generation's keys is updated in place
(local_updates), its action's entry replaced, so retirement removes the action. Without a held plan, as
on a first synchronization, after reopening, or after an undo past the held plans, and on a requested full rebuild,
every partition is prepared (AFF-04).

A kept copy is rebuilt instead of updated in place when unmanaged content uses any of its partition's resources
(CHG-06, OWN-08): anything but the destination collection, whose manifest names them, a scene linking it, whose view
layers hold a base for each of its objects, and the partition's own resources. So a resource someone else uses is
released intact, and a local update never changes what it uses. A kept copy whose published resources are
incomplete, as when the user deleted its object, is rebuilt too. A copy's published entries are those whose source
entity is its source path: an action's with its object's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import bpy

from ..binding.persistence import manifests
from ..core import _core
from . import datablock_removal

if TYPE_CHECKING:
    from collections.abc import Buffer, Collection, Mapping


@dataclass(frozen=True, slots=True)
class CopyUpdate:
    """What a local update changes of a kept copy (change-matrix.md "Actions")."""

    moved: bool  # its world matrix, and a sheared copy's split, differ
    bounds_changed: bool  # its bounds mesh is replaced, and its object pointed at the replacement
    participation_changed: bool  # its hide flags change
    cached_keys_removed: bool  # its object's action, which keys cached time codes, is unassigned and retired


@dataclass(frozen=True, slots=True)
class PartitionReplacement:
    """What a synchronization prepares, what it updates in place, and the published entries it replaces."""

    prepared_copy_indices: tuple[int, ...]  # in plan order
    # The published entries of the partitions prepared anew, of the copies the plan no longer has, and of the
    # actions of the copies whose cached keys are removed, by entry key.
    replaced_entry_keys: frozenset[str]
    # By copy index, in plan order: the kept copies updated in place, and what changes.
    updated_copies: Mapping[int, CopyUpdate] = field(default_factory=dict)


def partitions_to_replace(
    shown: _core.Plan | None, plan: _core.Plan, published: manifests.Manifest, destination: bpy.types.Collection
) -> PartitionReplacement:
    """What a synchronization of plan replaces: every partition without shown, else what differs from it.

    shown is the held plan of the generation published displays, or None, as for a full rebuild (AFF-04).
    destination holds published.
    """
    if shown is None:
        return every_partition(plan, published)
    return changed_partitions(shown, plan, published, destination)


def every_partition(plan: _core.Plan, published: manifests.Manifest) -> PartitionReplacement:
    """Every partition prepared, replacing every published entry: a full rebuild."""
    return PartitionReplacement(tuple(range(plan.copy_count)), frozenset(published.entries))


def changed_partitions(
    previous: _core.Plan, plan: _core.Plan, published: manifests.Manifest, destination: bpy.types.Collection
) -> PartitionReplacement:
    """The partitions of plan's copies that differ from previous's, the plan published is the display of."""
    diff = _core.diff_plans(previous, plan)
    matched = _indices(diff.previous_copy_indices)
    rebuilt = set(_indices(diff.rebuilt_copy_indices))
    moved, bounds = set(_indices(diff.moved_copy_indices)), set(_indices(diff.bounds_changed_copy_indices))
    participation = set(_indices(diff.participation_changed_copy_indices))
    keys_by_source: dict[str, set[str]] = {}
    action_keys: dict[str, str] = {}  # by source: the entry key of the action holding a copy's cached keys
    incomplete: set[str] = set()  # the sources of copies with a published resource gone
    for entry_key, entry in published.entries.items():
        if (identity := entry.identity) is None:
            continue
        keys_by_source.setdefault(identity.entity, set()).add(entry_key)
        if identity.role is manifests.RepresentationRole.ACTION:
            action_keys[identity.entity] = entry_key
        if entry.datablock is None:
            incomplete.add(identity.entity)
    sources = [entry.source_path for entry in plan.correspondence]
    previous_sources = [entry.source_path for entry in previous.correspondence]
    prepared: list[int] = []
    updated: dict[int, CopyUpdate] = {}
    for copy, old in enumerate(matched):
        source = sources[copy]
        if old < 0 or copy in rebuilt or source in incomplete or source not in keys_by_source:
            prepared.append(copy)
        elif copy in moved | bounds | participation or source in action_keys:
            updated[copy] = CopyUpdate(copy in moved, copy in bounds, copy in participation, source in action_keys)
    shared = _used_elsewhere({sources[c] for c in updated}, keys_by_source, published, destination)
    for copy in [c for c in updated if sources[c] in shared]:
        del updated[copy]
        prepared.append(copy)
    prepared.sort()
    replaced = {key for copy in prepared for key in keys_by_source.get(sources[copy], ())}
    replaced |= {action_keys[sources[c]] for c, change in updated.items() if change.cached_keys_removed}
    for old in _indices(diff.removed_previous_copy_indices):
        replaced |= keys_by_source.get(previous_sources[old], set())
    return PartitionReplacement(tuple(prepared), frozenset(replaced), updated)


def _used_elsewhere(
    sources: Collection[str],
    keys_by_source: Mapping[str, Collection[str]],
    published: manifests.Manifest,
    destination: bpy.types.Collection,
) -> set[str]:
    """The sources among sources whose copy's partition has a resource something besides the partition uses."""
    partitions: dict[str, set[int]] = {}  # by source: its partition's datablocks' session_uids
    kept: dict[bpy.types.ID, str] = {}  # the partitions' resources, to their sources
    for source in sources:
        entries = [published.entries[key] for key in keys_by_source[source]]
        partitions[source] = {e.datablock.session_uid for e in entries if e.datablock is not None}
        kept |= {e.datablock: source for e in entries if e.datablock is not None}
    if not kept:
        return set()
    # The destination, and each scene linking it, whose view layers have a base for each object it links. A scene that
    # also uses one otherwise, as its camera, isn't told apart.
    holders = {destination.session_uid} | {
        s.session_uid for s in bpy.data.scenes if destination in s.collection.children_recursive
    }
    users = datablock_removal.current_user_map(list(kept))
    return {
        source
        for datablock, source in kept.items()
        if {u.session_uid for u in users[datablock]} - partitions[source] - holders
    }


def _indices(buffer: Buffer) -> list[int]:
    with memoryview(buffer) as view:  # released before returning (SNAP-13)
        return view.tolist()
