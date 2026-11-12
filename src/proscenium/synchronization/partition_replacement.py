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
cached time code has, and a bounds mesh a cache call sampled, which a frames modifier shows. A copy's published entries
are those whose source entity is its source path: an action's with its object's. A shared datablock's entry, the
frames group's, is replaced once every entry using it is.
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
    found = _PublishedPartitions.of(published)
    keys_by_source, action_keys, incomplete = found.keys_by_source, found.action_keys, found.incomplete
    sources = [entry.source_path for entry in plan.correspondence]
    previous_sources = [entry.source_path for entry in previous.correspondence]
    sheared = [parent >= 0 for parent in _indices(plan.copy_shear_parent_resource_indices)]
    prepared: list[int] = []
    updated: dict[int, CopyUpdate] = {}
    for copy, old in enumerate(matched):
        source = sources[copy]
        unmatched = (source in found.parented) != sheared[copy] or source in found.sampled  # not the plan's
        if old < 0 or copy in rebuilt or source in incomplete or source not in keys_by_source or unmatched:
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
    return PartitionReplacement(tuple(prepared), frozenset(replaced | _unused_shared(published, replaced)), updated)


def _unused_shared(published: manifests.Manifest, replaced: Collection[str]) -> set[str]:
    """The keys of published's shared datablocks' entries that only replaced entries use."""
    used = {used for key, e in published.entries.items() if key not in replaced for used in e.dependency_entry_keys}
    return {key for key, e in published.entries.items() if e.identity is None and key not in used}


@dataclass(frozen=True, slots=True)
class _PublishedPartitions:
    """The published copies' partitions, by source entity."""

    keys_by_source: dict[str, set[str]]  # each copy's entries' keys
    action_keys: dict[str, str]  # the entry key of the action holding a copy's cached keys
    incomplete: set[str]  # the copies with a published resource gone
    parented: set[str]  # the copies with a published shear parent
    sampled: set[str]  # the copies whose entries use a shared datablock, the frames group a cache call sampled for

    @staticmethod
    def of(published: manifests.Manifest) -> _PublishedPartitions:
        """The partitions of published's copies."""
        found = _PublishedPartitions({}, {}, set(), set(), set())
        shared = {k for k, e in published.entries.items() if e.identity is None}
        for entry_key, entry in published.entries.items():
            if (identity := entry.identity) is None:
                continue
            found.keys_by_source.setdefault(identity.entity, set()).add(entry_key)
            if identity.role is manifests.RepresentationRole.ACTION:
                found.action_keys[identity.entity] = entry_key
            if identity.role is manifests.RepresentationRole.SHEAR_PARENT:
                found.parented.add(identity.entity)
            if entry.datablock is None:
                found.incomplete.add(identity.entity)
            if not shared.isdisjoint(entry.dependency_entry_keys):
                found.sampled.add(identity.entity)
        return found


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
