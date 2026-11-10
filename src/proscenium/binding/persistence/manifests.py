"""Ownership metadata: each binding's manifest of the resources it manages (lifecycle.md#ownership-and-lifecycle).

A manifest is a record on the binding's destination collection with one entry per managed resource, keyed by a
random entry key given when the resource is first published. An entry names the resource's datablock, its source
coverage, its representation role, its place among its copy's objects for a copy's roles, and the managed resources it
uses, by entry key; its ownership is the binding whose manifest holds it (OWN-01).

A key is never the resource's identity (lifecycle.md#representation-roles-and-resource-identities). A copy's resource's
entry records its identity (CopyResourceIdentity), so a prepared resource takes the key of the published entry whose
identity it has (existing_or_new_entry_keys). A batch's and a shared datablock's identities come from content keys,
which aren't persisted: M7 decides where it holds them.

Nothing is stored on the managed datablocks: a datablock is managed by the binding whose manifest names it (OWN-16).

- A duplicate or appended copy of managed content is unmanaged, and content two manifests name is ambiguous.
- Managed dependents come from inverting the uses (dependents). Unmanaged users are read from Blender's user graph
  when an operation needs them, since nothing persistent can track them.
- A manifest's pointers are users of the datablocks they name. Content the user deletes in the interface
  (Object > Delete) stays in the file, still named and so claimed, until a refresh or cleanup finds it linked
  nowhere; only bpy.data's remove clears the pointer. Reading unmanaged users has to discount the manifests (M7).

Reading a manifest reads every entry, so ownership of a datablock reads only the manifests among its users
(proscenium.binding.runtime.ownership). write_manifest_entries writes only the entries that change; an update gives
them without their datablocks (ManifestEntryChange), so it can't name a datablock another entry names.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

import bpy

from . import records
from .records import LoadedRecord, RefusedRecord, Schema

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence

MANIFEST_KEY = "manifest"

_ENTRY_KEY = re.compile(r"[0-9a-f]{32}")


class RepresentationRole(StrEnum):
    """Why a managed resource exists in its partition: the representation version's fixed vocabulary (ROLE-01).

    DECISIONS.md "Representation roles and resource identities" defines each. An entry stores the value; a stored entry
    naming any other role is refused.
    """

    # A drawn copy's partition. Each is identified by its source entity and place (CopyResourceIdentity).
    OBJECT = "object"
    SHEAR_PARENT = "shear parent"
    BOUNDS_MESH = "bounds mesh"
    ACTION = "action"
    # A batch's partition, identified by the content key its copies share.
    CARRIER = "carrier"
    POINTS_MESH = "points mesh"
    PROTOTYPE = "prototype"
    # A shared datablock, identified by its content key.
    MESH = "mesh"
    MATERIAL = "material"
    NODE_GROUP = "node group"

    @property
    def has_place(self) -> bool:
        """Whether the role is a drawn copy's, so its entry records its place."""
        return self in _COPY_ROLES


_COPY_ROLES = frozenset(
    {
        RepresentationRole.OBJECT,
        RepresentationRole.SHEAR_PARENT,
        RepresentationRole.BOUNDS_MESH,
        RepresentationRole.ACTION,
    }
)


class CopyResourceIdentity(NamedTuple):
    """A drawn copy's resource's identity, compared by equality: its role, source entity, and place (ROLE-03)."""

    role: RepresentationRole
    entity: str  # the source entity's path, an instance proxy's for an instanced copy
    place: int  # among the copy's objects


def new_entry_key() -> str:
    """A random entry key: 128 bits as 32 hex digits, short enough for an ID-property key."""
    return secrets.token_hex(16)


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One managed resource."""

    datablock: bpy.types.ID | None  # None once the user deletes it: removing a datablock clears pointers to it
    covers: Sequence[str]  # the source entities it represents: composed-stage paths, possibly many; a copy's, one
    role: RepresentationRole  # why it exists; a record stores the value
    uses: Sequence[str]  # the entry keys of the managed resources it depends on
    place: int | None = None  # its place among its copy's objects for a copy's role, else None

    def __post_init__(self) -> None:
        if not isinstance(self.datablock, bpy.types.ID | None):
            raise TypeError("an entry's datablock is not one")
        # The items in covers and uses aren't checked here, since a manifest can have thousands of
        # entries. A bad path in covers is caught when it's resolved. A bad item in uses is caught by
        # Manifest.__post_init__, which refuses any item that isn't another entry's key.
        if type(self.covers) not in (list, tuple) or type(self.uses) not in (list, tuple):
            raise TypeError("an entry covers a list of source-entity paths and uses a list of resources")
        # Tuples, so a manifest's entries can't be changed through one.
        object.__setattr__(self, "covers", tuple(self.covers))
        object.__setattr__(self, "uses", tuple(self.uses))
        role = RepresentationRole(self.role)  # ValueError for one outside the vocabulary
        object.__setattr__(self, "role", role)
        if role.has_place:
            if type(self.place) is not int or self.place < 0 or len(self.covers) != 1:
                raise ValueError(f"a {role} entry covers one source entity and has a place among its copy's objects")
        elif self.place is not None:
            raise ValueError(f"a {role} entry has no place: only a copy's roles do")

    @property
    def identity(self) -> CopyResourceIdentity | None:
        """The resource's identity, for a copy's role; None for a content-keyed one, whose identity isn't stored."""
        if self.place is None:
            return None
        return CopyResourceIdentity(self.role, self.covers[0], self.place)


@dataclass(frozen=True, slots=True)
class ManifestEntryChange:
    """A changed entry without its datablock, which comes from the entry it changes or from what the operation made.

    So an update can't name a datablock another entry names (Manifest.updated). Checked when the entry is built.
    """

    covers: Sequence[str]
    role: RepresentationRole
    uses: Sequence[str]
    place: int | None = None

    def entry_for_datablock(self, datablock: bpy.types.ID | None) -> ManifestEntry:
        """The entry naming datablock."""
        return ManifestEntry(datablock, self.covers, self.role, self.uses, self.place)


@dataclass(frozen=True)
class Manifest:
    """An immutable value: its entries are a read-only view of a dict nothing else holds."""

    entries: Mapping[str, ManifestEntry]  # entry key -> its entry

    def __post_init__(self) -> None:
        # A stored manifest's entries are plain groups; build them.
        entries = {key: e if isinstance(e, ManifestEntry) else ManifestEntry(**e) for key, e in self.entries.items()}
        object.__setattr__(self, "entries", MappingProxyType(entries))
        _check_keys(entries)
        if missing := {used for e in entries.values() for used in e.uses} - entries.keys():
            raise ValueError(f"entries use resources the manifest doesn't have: {sorted(missing)}")
        named = [e.datablock for e in entries.values() if e.datablock is not None]
        if len(set(named)) != len(named):
            raise ValueError("two entries name one datablock")

    def updated(
        self,
        changed: Mapping[str, ManifestEntryChange],
        removed: Collection[str] = (),
        created: Mapping[str, bpy.types.ID] = MappingProxyType({}),
    ) -> Manifest:
        """This manifest with changed's entries added or replaced and removed's deleted, checked as a whole one is.

        A changed entry names created's datablock under its key, which the operation made, so no manifest names it yet;
        otherwise the datablock the entry it replaces names. So a datablock never moves between keys, and an update
        names no datablock twice without reading which entry names it. The checks cost what changes, plus a scan of
        every entry's uses when removing; the result copies the entries. Raises ValueError or TypeError over an update
        that makes no manifest.
        """
        removed = frozenset(removed)  # tested once per entry and per use: a caller's list would make each a search
        if not changed.keys().isdisjoint(removed):
            raise ValueError("an update both changes and removes a resource")
        _check_keys(changed)
        if missing := removed - self.entries.keys():
            raise ValueError(f"removes resources the manifest doesn't have: {sorted(missing)}")
        if unchanged := created.keys() - changed.keys():
            raise ValueError(f"datablocks made for resources the update doesn't change: {sorted(unchanged)}")
        if len(set(created.values())) != len(created):
            raise ValueError("two entries name one datablock")
        made = {}
        for entry_key, change in changed.items():
            if type(change) is not ManifestEntryChange:
                raise TypeError("a changed entry is not a ManifestEntryChange")
            if entry_key in created:
                datablock = created[entry_key]
            elif entry_key in self.entries:
                datablock = self.entries[entry_key].datablock
            else:
                raise ValueError(f"a new resource has no datablock made for it: {entry_key}")
            entry = change.entry_for_datablock(datablock)
            # Checked here, unlike in a whole manifest, since only the changed entries are.
            if not all(type(item) is str for item in (*entry.covers, *entry.uses)):
                raise TypeError("an entry covers source-entity paths and uses entry keys, all strings")
            made[entry_key] = entry
        entries = {key: e for key, e in self.entries.items() if key not in removed} | made
        used = {u for e in made.values() for u in e.uses}
        if removed:  # a scan, but of values in memory
            used |= {u for e in entries.values() for u in e.uses if u in removed}
        if missing := used - entries.keys():
            raise ValueError(f"entries use resources the manifest doesn't have: {sorted(missing)}")
        manifest = object.__new__(Manifest)  # checked above, so not again in __post_init__
        object.__setattr__(manifest, "entries", MappingProxyType(entries))
        return manifest


def _check_keys(entries: Mapping[str, object]) -> None:
    if bad := [key for key in entries if type(key) is not str or not _ENTRY_KEY.fullmatch(key)]:
        raise ValueError(f"entry keys are 32 hex digits, not {sorted(map(repr, bad))}")


MANIFEST = Schema("manifest", version=1, record_type=Manifest)


def read_manifest(destination: bpy.types.Collection) -> LoadedRecord[Manifest] | RefusedRecord | None:
    """The destination's manifest, why it can't be read, or None if it has none."""
    return records.read(destination, MANIFEST_KEY, MANIFEST)


def write_manifest(destination: bpy.types.Collection, manifest: Manifest) -> LoadedRecord[Manifest]:
    """Store the destination's manifest whole; the manifest as reading it back would give it.

    Raises RefusedRecordError, changing nothing, over a stored manifest that can't be read.
    """
    records.write(destination, MANIFEST_KEY, MANIFEST, manifest)
    return LoadedRecord(manifest, MANIFEST.version)


def remove_manifest(destination: bpy.types.Collection) -> None:
    """Remove the destination's manifest, if it has one; raises as write_manifest does."""
    records.remove(destination, MANIFEST_KEY, MANIFEST)


def write_manifest_entries(
    destination: bpy.types.Collection, manifest: Manifest, changed: Collection[str], removed: Collection[str]
) -> LoadedRecord[Manifest]:
    """Store manifest, writing only the entries under changed and removed; the manifest as reading it would give it.

    manifest differs from the stored one only in those entries (records.write_items). Raises as write_manifest does.
    """
    records.write_items(destination, MANIFEST_KEY, MANIFEST, manifest, "entries", changed, removed)
    return LoadedRecord(manifest, MANIFEST.version)


def dependents(manifest: Manifest) -> Mapping[str, set[str]]:
    """For each resource, the managed resources in the same manifest that use it."""
    found: dict[str, set[str]] = {entry_key: set() for entry_key in manifest.entries}
    for entry_key, entry in manifest.entries.items():
        for used in entry.uses:
            found[used].add(entry_key)
    return found


def existing_or_new_entry_keys(manifest: Manifest, identities: Iterable[CopyResourceIdentity]) -> list[str]:
    """For each identity, the key of manifest's entry with it, or a new key if none has it (ROLE-05).

    A prepared resource that represents what a published one does takes its key, so publication replaces that entry.
    Reads every entry once.
    """
    published = {identity: key for key, e in manifest.entries.items() if (identity := e.identity) is not None}
    return [published.get(identity) or new_entry_key() for identity in identities]
