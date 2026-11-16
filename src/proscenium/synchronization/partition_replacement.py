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
incomplete, as when the user deleted its object, is rebuilt too, as is one whose published partition isn't the
plan's: a shear parent the plan doesn't have, or the reverse, as when a cache call gave a copy one for a shear only a
cached time code has, a bounds mesh a cache call sampled, which a frames modifier shows, and a second object a cache
call made for the form, box or marker, a placeholder takes only at cached time codes. A copy's published entries
are those whose source entity is its source path: an action's with its object's. A shared datablock's entry, the
frames group's, is replaced once every entry using it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import bpy

from ..binding.runtime import kept_manifests
from ..core import _core
from . import datablock_removal

if TYPE_CHECKING:
    from collections.abc import Buffer, Collection, Mapping

    from ..binding.persistence import manifests
    from ..binding.runtime import copy_partitions


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
    """The partitions of plan's copies that differ from previous's, the plan published is the display of.

    The core gives the plan diff and plan's copies' source paths; the published manifest's partitions are the ones
    kept_manifests keeps beside it, so no refresh groups every entry.
    """
    diff = _core.diff_plans(previous, plan)
    matched = _indices(diff.previous_copy_indices)
    rebuilt = set(_indices(diff.rebuilt_copy_indices))
    moved, bounds = set(_indices(diff.moved_copy_indices)), set(_indices(diff.bounds_changed_copy_indices))
    participation = set(_indices(diff.participation_changed_copy_indices))
    partitions = kept_manifests.published_partitions(destination, published)
    sources = [entry.source_path for entry in plan.correspondence]
    sheared = [parent >= 0 for parent in _indices(plan.copy_shear_parent_resource_indices)]
    prepared: list[int] = []
    updated: dict[int, CopyUpdate] = {}
    for copy, old in enumerate(matched):
        partition = partitions.partition(sources[copy])
        unmatched = partition is not None and (
            partition.parented != sheared[copy] or partition.sampled or partition.doubled
        )
        if old < 0 or copy in rebuilt or partition is None or partition.incomplete or unmatched:
            prepared.append(copy)
        elif copy in moved or copy in bounds or copy in participation or partition.action_entry_key is not None:
            keyed = partition.action_entry_key is not None
            updated[copy] = CopyUpdate(copy in moved, copy in bounds, copy in participation, keyed)
    shared = _used_elsewhere({sources[c] for c in updated}, partitions, published, destination)
    for copy in [c for c in updated if sources[c] in shared]:
        del updated[copy]
        prepared.append(copy)
    prepared.sort()

    def keys(source: str) -> frozenset[str]:
        partition = partitions.partition(source)
        return frozenset() if partition is None else partition.entry_keys

    replaced = {key for copy in prepared for key in keys(sources[copy])}
    for copy, change in updated.items():
        if change.cached_keys_removed and (partition := partitions.partition(sources[copy])) is not None:
            replaced.add(str(partition.action_entry_key))
    removed = _indices(diff.removed_previous_copy_indices)
    # A matched copy has its counterpart's source path, so previous's are plan's and the removed copies'.
    removed_sources = {previous.correspondence[old].source_path for old in removed} if removed else set()
    for source in removed_sources:
        replaced |= keys(source)
    # And the copies a cache call built for its time codes alone, which neither plan has.
    for source in partitions.source_paths() - set(sources) - removed_sources:
        replaced |= keys(source)
    return PartitionReplacement(tuple(prepared), frozenset(replaced | partitions.unused_shared(replaced)), updated)


def _used_elsewhere(
    sources: Collection[str],
    published_partitions: copy_partitions.PublishedPartitions,
    published: manifests.Manifest,
    destination: bpy.types.Collection,
) -> set[str]:
    """The sources among sources whose copy's partition has a resource something besides the partition uses."""
    partitions: dict[str, set[int]] = {}  # by source: its partition's datablocks' session_uids
    kept: dict[bpy.types.ID, str] = {}  # the partitions' resources, to their sources
    for source in sources:
        partition = published_partitions.partition(source)
        entries = [] if partition is None else [published.entries[key] for key in partition.entry_keys]
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
