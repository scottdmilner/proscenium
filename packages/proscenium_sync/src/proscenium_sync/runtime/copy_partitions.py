"""A published manifest's copies' partitions, by source entity: what a refresh decides from on the manifest's side.

synchronization.partition_replacement decides each copy from the plan diff and these: a copy's entries, whether a
resource of it is gone, whether it has a shear parent, a second object, an action keying cached time codes, or an
entry using a shared datablock, which only a cache call gives it; and which shared datablocks only some entries use.
Grouping every entry cost 11 ms on ALab's 13,358 entries at each refresh, so kept_manifests keeps a kept manifest's
grouping beside it and gives it each write by entry's changed and removed entries (replace_entries), which regroups
only the copies they cover.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from proscenium_sync.persistence import manifests

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Set


@dataclass(frozen=True, slots=True)
class CopyPartition:
    """A published copy's partition: its entries, and what of it a refresh must prepare anew or update in place."""

    entry_keys: frozenset[str]
    action_entry_key: str | None  # the action holding its cached keys, or None
    incomplete: bool  # a published resource of it is gone
    parented: bool  # it has a published shear parent
    sampled: bool  # an entry of it uses a shared datablock: a cache call sampled it
    doubled: bool  # it has a second object, a cache call's for a form its plan didn't draw


@dataclass(frozen=True, slots=True)
class _EntryFacts:
    """What grouping reads of an entry."""

    source_path: str | None  # its copy's source entity; None for a shared datablock's entry
    role: manifests.RepresentationRole
    object_index_in_copy: int | None
    has_datablock: bool
    dependency_entry_keys: tuple[str, ...]

    @staticmethod
    def of(entry: manifests.ManifestEntry) -> _EntryFacts:
        identity = entry.identity
        return _EntryFacts(
            None if identity is None else identity.entity,
            entry.role,
            entry.object_index_in_copy,
            entry.datablock is not None,
            tuple(entry.dependency_entry_keys),
        )


class PublishedPartitions:
    """A manifest's copies' partitions, by source entity, kept in step with its writes by entry."""

    _facts_by_entry_key: dict[str, _EntryFacts]
    _entry_keys_by_source: dict[str, set[str]]
    _user_keys_by_entry_key: dict[str, set[str]]  # the entries using each
    _shared_entry_keys: set[str]
    _partitions_by_source: dict[str, CopyPartition]

    def __init__(self, manifest: manifests.Manifest) -> None:
        self._facts_by_entry_key = {}
        self._entry_keys_by_source = {}
        self._user_keys_by_entry_key = {}
        self._shared_entry_keys = set()
        self._partitions_by_source = {}
        self.replace_entries(manifest, manifest.entries, ())

    def replace_entries(self, manifest: manifests.Manifest, changed: Iterable[str], removed: Iterable[str]) -> None:
        """Take manifest's entries under changed, replacing or adding them, and drop those under removed.

        manifest is the one a write by entry stored; only the partitions of the copies the entries cover are grouped
        again.
        """
        regrouped: set[str] = set()
        for entry_key in removed:
            self._remove(entry_key, regrouped)
        for entry_key in changed:
            self._remove(entry_key, regrouped)
            facts = _EntryFacts.of(manifest.entries[entry_key])
            self._facts_by_entry_key[entry_key] = facts
            for used in facts.dependency_entry_keys:
                self._user_keys_by_entry_key.setdefault(used, set()).add(entry_key)
            if facts.source_path is None:
                self._shared_entry_keys.add(entry_key)
            else:
                self._entry_keys_by_source.setdefault(facts.source_path, set()).add(entry_key)
                regrouped.add(facts.source_path)
        for source in regrouped:
            self._regroup(source)

    def partition(self, source_path: str) -> CopyPartition | None:
        """The partition of the published copy of source_path, or None for one no published copy has."""
        return self._partitions_by_source.get(source_path)

    def source_paths(self) -> Set[str]:
        """The source entities of the published copies."""
        return self._partitions_by_source.keys()

    def unused_shared(self, replaced: Collection[str]) -> set[str]:
        """The keys of the shared datablocks' entries that no entry outside replaced uses."""
        users, replaced_keys = self._user_keys_by_entry_key, set(replaced)
        return {k for k in self._shared_entry_keys if users.get(k, set()) <= replaced_keys}

    def _remove(self, entry_key: str, regrouped: set[str]) -> None:
        facts = self._facts_by_entry_key.pop(entry_key, None)
        if facts is None:
            return
        for used in facts.dependency_entry_keys:
            users = self._user_keys_by_entry_key.get(used)
            if users is not None:
                users.discard(entry_key)
                if not users:
                    del self._user_keys_by_entry_key[used]
        if facts.source_path is None:
            self._shared_entry_keys.discard(entry_key)
        else:
            self._entry_keys_by_source[facts.source_path].discard(entry_key)
            regrouped.add(facts.source_path)

    def _regroup(self, source: str) -> None:
        keys = self._entry_keys_by_source.get(source)
        if not keys:
            self._entry_keys_by_source.pop(source, None)
            self._partitions_by_source.pop(source, None)
            return
        facts = [(key, self._facts_by_entry_key[key]) for key in keys]
        role = manifests.RepresentationRole
        self._partitions_by_source[source] = CopyPartition(
            frozenset(keys),
            next((key for key, f in facts if f.role is role.ACTION), None),
            any(not f.has_datablock for _, f in facts),
            any(f.role is role.SHEAR_PARENT for _, f in facts),
            any(not self._shared_entry_keys.isdisjoint(f.dependency_entry_keys) for _, f in facts),
            any(f.role is role.OBJECT and (f.object_index_in_copy or 0) > 0 for _, f in facts),
        )
