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
    from collections.abc import Mapping

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
        if not isinstance(self.covers, list) or not all(type(path) is str for path in self.covers):
            raise TypeError("an entry covers a list of source-entity paths")
        if type(self.role) is not str or not self.role:
            raise ValueError("an entry has a representation role")
        if not isinstance(self.uses, list) or not all(type(resource) is str for resource in self.uses):
            raise TypeError("an entry uses a list of resource identities")


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


def binding_manifest(binding_id: str) -> Loaded[Manifest] | Refused | None:
    """One binding's manifest, read through its configuration's destination, for operations on that binding.

    Refused if the configuration or the manifest can't be read; None if the binding has no
    destination (it was removed) or no manifest yet. Raises KeyError if no binding has this
    identifier. Whether another manifest also names one of its datablocks is the file-wide
    question claims() answers.
    """
    if (found := bindings.find(binding_id)) is None:
        raise KeyError(binding_id)
    config = found[1]
    if isinstance(config, Refused):
        return config
    destination = config.record.destination
    return None if destination is None else read_manifest(destination)


def write_manifest(destination: bpy.types.Collection, manifest: Manifest) -> None:
    """Raises RecordRefused, changing nothing, over a stored manifest that can't be read."""
    records.write(destination, MANIFEST_KEY, MANIFEST, manifest)


def claims() -> tuple[dict[bpy.types.ID, list[Claim]], list[Refused]]:
    """Every datablock a manifest names, with the claims on it, and the manifests that can't be read.

    One claim means the datablock is managed by that binding; two or more, from different
    manifests, that it is ambiguous: it is reported, never automatically claimed or deleted
    (OWN-09); none, that it is unmanaged. That judgment needs every manifest that could name the
    datablock, so this reads all of them and can't be limited to some bindings: it is what the
    runtime index of ownership is built from, once after a file load, undo, or redo and after each
    publication, not something to call per operation. For one binding's own resources, use
    binding_manifest().

    Each manifest is read once, though several binding configurations can point at its
    destination, as a linked-copy scene's do. A manifest that can't be read claims nothing, so its
    content has no ownership evidence until it is repaired. Datablock references don't survive an
    operator call or undo: use the result at once.
    """
    destinations: dict[bpy.types.Collection, str] = {}  # each destination a configuration names -> its binding
    for _scene, binding_id, config in bindings.all_bindings():
        if not isinstance(config, Refused) and config.record.destination is not None:
            destinations.setdefault(config.record.destination, binding_id)
    found: dict[bpy.types.ID, list[Claim]] = defaultdict(list)
    unreadable: list[Refused] = []
    for destination, binding_id in destinations.items():
        manifest = read_manifest(destination)
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
