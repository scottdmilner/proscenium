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
built from it, not through these functions.

A manifest's pointers are users of the datablocks they name. So managed content the user deletes
in the interface (Object > Delete) stays in the file, still named and so still claimed, until a
refresh or cleanup finds it linked nowhere; only bpy.data's remove clears the pointer. And
Blender's user graph lists each manifest among a managed datablock's users, which reading
unmanaged users has to discount (M7).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy

from . import bindings, records
from .records import Loaded, Refused, Schema

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

MANIFEST_KEY = "manifest"


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One managed resource."""

    datablock: bpy.types.ID | None  # None once the user deletes it: removing a datablock clears pointers to it
    covers: list[str]  # the source entities it represents: composed-stage paths, possibly many
    role: str  # why it exists; M5 defines the roles
    uses: list[str]  # the resource identities of the managed resources it depends on

    def __post_init__(self) -> None:
        if not isinstance(self.datablock, bpy.types.ID | None):
            raise TypeError("an entry's datablock is not one")
        # The items in covers and uses aren't checked here, since a manifest can have thousands of
        # entries. A bad path in covers is caught when it's resolved. A bad item in uses is caught by
        # Manifest.__post_init__, which refuses any item that isn't another entry's resource identity.
        if type(self.covers) is not list or type(self.uses) is not list:
            raise TypeError("an entry covers a list of source-entity paths and uses a list of resources")
        if type(self.role) is not str or not self.role:
            raise ValueError("an entry has a representation role")


@dataclass(frozen=True)
class Manifest:
    entries: dict[str, ManifestEntry]  # resource identity -> its entry

    def __post_init__(self) -> None:
        # A stored manifest's entries are plain groups; build them.
        entries = {key: e if isinstance(e, ManifestEntry) else ManifestEntry(**e) for key, e in self.entries.items()}
        object.__setattr__(self, "entries", entries)
        if missing := {used for e in entries.values() for used in e.uses} - entries.keys():
            raise ValueError(f"entries use resources the manifest doesn't have: {sorted(missing)}")
        named = [e.datablock for e in entries.values() if e.datablock is not None]
        if len(set(named)) != len(named):
            raise ValueError("two entries name one datablock")


MANIFEST = Schema("manifest", version=1, record=Manifest)


@dataclass(frozen=True, slots=True)
class Claim:
    """A manifest entry naming a datablock: the evidence that a binding manages it (OWN-16).

    A manifest names a datablock at most once, so each claim on a datablock comes from a different
    manifest, and two or more mean it is ambiguous (see claims()). A binding's copies share its
    identity, so the destination says which manifest a claim comes from. Like the datablocks it
    sits beside, it doesn't survive an operator call or undo.
    """

    binding_id: str  # the binding whose manifest holds the entry
    destination: bpy.types.Collection  # the collection holding that manifest
    resource_id: str  # the entry's key in that manifest


def read_manifest(destination: bpy.types.Collection) -> Loaded[Manifest] | Refused | None:
    return records.read(destination, MANIFEST_KEY, MANIFEST)


def write_manifest(destination: bpy.types.Collection, manifest: Manifest) -> None:
    """Raises RecordRefused, changing nothing, over a stored manifest that can't be read."""
    records.write(destination, MANIFEST_KEY, MANIFEST, manifest)


def claims() -> tuple[dict[bpy.types.ID, list[Claim]], list[Refused]]:
    """claims_from() over every binding's manifest, read from the records now.

    Each manifest is read once, though several configurations can name its destination, as a
    linked-copy scene's do. The runtime indexes (proscenium.indexes) keep this for the session;
    reading it again here is for when they can't be used.
    """
    manifests = []
    seen: set[bpy.types.Collection] = set()
    for _scene, binding_id, config in bindings.all_bindings():
        destination = None if isinstance(config, Refused) else config.record.destination
        if destination is not None and destination not in seen:
            seen.add(destination)
            manifests.append((binding_id, destination, read_manifest(destination)))
    return claims_from(manifests)


def claims_from(
    manifests: Iterable[tuple[str, bpy.types.Collection, Loaded[Manifest] | Refused | None]],
) -> tuple[dict[bpy.types.ID, list[Claim]], list[Refused]]:
    """Every datablock the manifests name, with the claims on it, and the manifests that can't be read.

    manifests gives each binding's destination and the manifest there; several bindings can name
    one destination, as a linked-copy scene's configurations do, and it counts once. One claim means
    the datablock is managed by that binding; two or more, from different manifests, that it is
    ambiguous: it is reported, never automatically claimed or deleted (OWN-09); none, that it is
    unmanaged. That judgment needs every manifest that could name the datablock, so it can't be made
    from some bindings' manifests alone. A manifest that can't be read claims nothing, so its content
    has no ownership evidence until it is repaired. Datablock references don't survive an operator
    call or undo: use the result at once.
    """
    found: dict[bpy.types.ID, list[Claim]] = defaultdict(list)
    unreadable: list[Refused] = []
    seen: set[bpy.types.Collection] = set()
    for binding_id, destination, manifest in manifests:
        if destination in seen:
            continue
        seen.add(destination)
        if isinstance(manifest, Refused):
            unreadable.append(manifest)
        elif manifest is not None:
            for resource_id, entry in manifest.record.entries.items():
                if entry.datablock is not None:
                    found[entry.datablock].append(Claim(binding_id, destination, resource_id))
    return dict(found), unreadable


def dependents(manifest: Manifest) -> Mapping[str, set[str]]:
    """For each resource, the managed resources in the same manifest that use it."""
    found: dict[str, set[str]] = {resource_id: set() for resource_id in manifest.entries}
    for resource_id, entry in manifest.entries.items():
        for used in entry.uses:
            found[used].add(resource_id)
    return found
