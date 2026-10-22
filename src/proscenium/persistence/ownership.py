"""Ownership metadata: each binding's manifest of the resources it manages (lifecycle.md#ownership-and-lifecycle).

A binding's manifest is a record on its destination collection, with one entry per managed
resource, keyed by the resource's identity. An entry names the resource's datablock and records
its source coverage, representation role, and the managed resources it uses; its ownership is the
binding whose manifest holds it. These are the separate concepts ownership records keep (OWN-01).

Nothing is stored on the managed datablocks. A datablock is managed by the binding whose manifest
names it (OWN-16), so a duplicate or appended copy of managed content is unmanaged, and content
two manifests name is ambiguous. Managed dependents are found by inverting the uses; unmanaged
users are read from Blender's user graph when an operation needs them, since nothing persistent
can track them.

Reading a manifest reads every entry, so the operations that run often go through runtime indexes
built from it, not through these functions. Writing one can write only the entries that change
(write_entries), so an incremental refresh costs what it changes.

A manifest's pointers are users of the datablocks they name. So managed content the user deletes
in the interface (Object > Delete) stays in the file, still named and so still claimed, until a
refresh or cleanup finds it linked nowhere; only bpy.data's remove clears the pointer. And
Blender's user graph lists each manifest among a managed datablock's users, which reading
unmanaged users has to discount (M7).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

import bpy

from . import records
from .records import Loaded, Refused, Schema

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping, Sequence

MANIFEST_KEY = "manifest"


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One managed resource."""

    datablock: bpy.types.ID | None  # None once the user deletes it: removing a datablock clears pointers to it
    covers: Sequence[str]  # the source entities it represents: composed-stage paths, possibly many
    role: str  # why it exists; M5 defines the roles
    uses: Sequence[str]  # the resource identities of the managed resources it depends on

    def __post_init__(self) -> None:
        if not isinstance(self.datablock, bpy.types.ID | None):
            raise TypeError("an entry's datablock is not one")
        # The items in covers and uses aren't checked here, since a manifest can have thousands of
        # entries. A bad path in covers is caught when it's resolved. A bad item in uses is caught by
        # Manifest.__post_init__, which refuses any item that isn't another entry's resource identity.
        if type(self.covers) not in (list, tuple) or type(self.uses) not in (list, tuple):
            raise TypeError("an entry covers a list of source-entity paths and uses a list of resources")
        # Tuples, so the cache that hands entries out (proscenium.runtime.indexes) can't be changed through one.
        object.__setattr__(self, "covers", tuple(self.covers))
        object.__setattr__(self, "uses", tuple(self.uses))
        if type(self.role) is not str or not self.role:
            raise ValueError("an entry has a representation role")


@dataclass(frozen=True)
class Manifest:
    """An immutable value: its entries are a read-only view of a dict nothing else holds."""

    entries: Mapping[str, ManifestEntry]  # resource identity -> its entry

    def __post_init__(self) -> None:
        # A stored manifest's entries are plain groups; build them.
        entries = {key: e if isinstance(e, ManifestEntry) else ManifestEntry(**e) for key, e in self.entries.items()}
        object.__setattr__(self, "entries", MappingProxyType(entries))
        if missing := {used for e in entries.values() for used in e.uses} - entries.keys():
            raise ValueError(f"entries use resources the manifest doesn't have: {sorted(missing)}")
        named = [e.datablock for e in entries.values() if e.datablock is not None]
        if len(set(named)) != len(named):
            raise ValueError("two entries name one datablock")

    def updated(
        self, changed: Mapping[str, ManifestEntry], removed: Collection[str], naming: Callable[[int], str | None]
    ) -> Manifest:
        """This manifest with changed's entries added or replaced and removed's deleted, checked as a whole one
        is. The checks cost what changes, plus, with removals, a scan of every entry's uses; building the
        result copies the entries.

        naming gives the key of this manifest's entry naming a datablock, by session_uid, or None; the
        ownership index has it. Raises ValueError or TypeError over an update that makes no manifest.
        """
        removed = frozenset(removed)  # tested once per entry and per use: a caller's list would make each a search
        if not changed.keys().isdisjoint(removed):
            raise ValueError("an update both changes and removes a resource")
        if missing := removed - self.entries.keys():
            raise ValueError(f"removes resources the manifest doesn't have: {sorted(missing)}")
        for entry in changed.values():
            if type(entry) is not ManifestEntry:
                raise TypeError("a changed entry is not a ManifestEntry")
            # Checked here, unlike in a whole manifest, since only the changed entries are.
            if not all(type(item) is str for item in (*entry.covers, *entry.uses)):
                raise TypeError("an entry covers source-entity paths and uses resource identities, all strings")
        entries = {key: e for key, e in self.entries.items() if key not in removed} | dict(changed)
        used = {u for e in changed.values() for u in e.uses}
        if removed:  # a scan, but of values in memory
            used |= {u for e in entries.values() for u in e.uses if u in removed}
        if missing := used - entries.keys():
            raise ValueError(f"entries use resources the manifest doesn't have: {sorted(missing)}")
        named = [e.datablock for e in changed.values() if e.datablock is not None]
        if len(set(named)) != len(named) or any(
            (key := naming(d.session_uid)) is not None and key not in changed and key not in removed for d in named
        ):
            raise ValueError("two entries name one datablock")
        manifest = object.__new__(Manifest)  # checked above, so not again in __post_init__
        object.__setattr__(manifest, "entries", MappingProxyType(entries))
        return manifest


MANIFEST = Schema("manifest", version=1, record=Manifest)


@dataclass(frozen=True, slots=True)
class Claim:
    """A manifest entry naming a datablock: the evidence that a binding manages it (OWN-16).

    A manifest names a datablock at most once, so each claim on a datablock comes from a different
    manifest. One claim means the datablock is managed by that binding; two or more, that it is
    ambiguous: it is reported, never automatically claimed or deleted (OWN-09); none, that it is
    unmanaged. That judgment needs every manifest that could name the datablock, so the runtime
    indexes (proscenium.runtime.indexes) index every binding's. Each destination's manifest counts once,
    though several configurations can name it, as a linked-copy scene's do. A manifest that can't be
    read claims nothing, so its content has no ownership evidence until it is repaired. A binding's
    copies share its identity, so the destination says which manifest a claim comes from. Like the
    datablocks it sits beside, it doesn't survive an operator call or undo.
    """

    binding_id: str  # the binding whose manifest holds the entry
    destination: bpy.types.Collection  # the collection holding that manifest
    resource_id: str  # the entry's key in that manifest


def read_manifest(destination: bpy.types.Collection) -> Loaded[Manifest] | Refused | None:
    return records.read(destination, MANIFEST_KEY, MANIFEST)


def write_manifest(destination: bpy.types.Collection, manifest: Manifest) -> None:
    """Raises RecordRefused, changing nothing, over a stored manifest that can't be read."""
    records.write(destination, MANIFEST_KEY, MANIFEST, manifest)


def write_entries(
    destination: bpy.types.Collection, manifest: Manifest, changed: Collection[str], removed: Collection[str]
) -> None:
    """Store manifest, which differs from the stored one only in the entries under changed and removed,
    writing only those (records.write_items). Raises as write_manifest does, and KeyError, changing nothing,
    for a resource identity too long for an ID-property key."""
    records.write_items(destination, MANIFEST_KEY, MANIFEST, manifest, "entries", changed, removed)


def dependents(manifest: Manifest) -> Mapping[str, set[str]]:
    """For each resource, the managed resources in the same manifest that use it."""
    found: dict[str, set[str]] = {resource_id: set() for resource_id in manifest.entries}
    for resource_id, entry in manifest.entries.items():
        for used in entry.uses:
            found[used].add(resource_id)
    return found
