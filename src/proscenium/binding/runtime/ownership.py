"""Ownership: whether each datablock is managed, from the manifests that name it (lifecycle.md#ownership-and-lifecycle).

of(datablock) answers from the datablock's users (bpy.data.user_map): a manifest's pointer is a user of the datablock
it names, so the collections holding binding records among its users are the only ones whose manifests can claim it,
and only those are read. A copy's manifest counts, and one whose target scene was removed, so content a copy names is
ambiguous rather than one binding's (DECISIONS.md "Binding records read when called").

Also a binding's manifest, read from its destination when asked for, and manifest writes, whole or by entry. A
removed datablock's pointer is cleared in the record, so no manifest read names one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

import bpy

from ..persistence import binding_records, manifests
from ..persistence.id_property_records import LoadedRecord, RefusedRecord, RefusedRecordError
from . import binding_operations

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from ..source_access import BindingId


@dataclass(frozen=True, slots=True)
class Claim:
    """A manifest entry naming a datablock: the evidence that a binding manages it (OWN-16).

    Each destination's manifest counts once, and a manifest that can't be read claims nothing. A claim doesn't survive
    an operator call or undo.
    """

    binding_id: BindingId  # the first binding whose record the manifest's collection holds
    destination: bpy.types.Collection  # the collection holding that manifest; a binding's copies share binding_id
    entry_key: str  # the entry's key in that manifest


class OwnershipStatus(StrEnum):
    """What the claims on a datablock mean."""

    UNMANAGED = "unmanaged"  # no claims
    MANAGED = "managed"  # one: the binding whose manifest holds it manages it
    AMBIGUOUS = "ambiguous"  # two or more, from different manifests: reported, never claimed or deleted (OWN-09)


@dataclass(frozen=True, slots=True)
class Ownership:
    """Whether a datablock is managed, and the claims that say so."""

    claims: tuple[Claim, ...]  # by the name of the collection holding each manifest

    @property
    def status(self) -> OwnershipStatus:
        """What the claims mean."""
        if not self.claims:
            return OwnershipStatus.UNMANAGED
        return OwnershipStatus.MANAGED if len(self.claims) == 1 else OwnershipStatus.AMBIGUOUS


def of(datablock: bpy.types.ID) -> Ownership:
    """Whether datablock is managed, and by which binding: the claims on it in every manifest naming it."""
    holders = [
        user
        for user in bpy.data.user_map(subset=[datablock])[datablock]
        if isinstance(user, bpy.types.Collection) and user.library is None and binding_records.binding_ids(user)
    ]
    claims = []
    for holder in sorted(holders, key=lambda c: c.name):
        manifest = manifests.read_manifest(holder)
        if isinstance(manifest, LoadedRecord):  # one that can't be read claims nothing until it is repaired
            claimant = binding_records.binding_ids(holder)[0]
            claims += [
                Claim(claimant, holder, k) for k, e in manifest.record.entries.items() if e.datablock == datablock
            ]
    return Ownership(tuple(claims))


def manifest(binding_id: BindingId) -> LoadedRecord[manifests.Manifest] | RefusedRecord | None:
    """A binding's manifest, read from its destination: why it can't be read, or None if it has none yet.

    Raises KeyError if no binding has this identifier, and DisabledBindingError if it has no canonical candidate.
    """
    return manifests.read_manifest(binding_operations.require_canonical_binding_record(binding_id).collection)


def set_manifest(binding_id: BindingId, manifest: manifests.Manifest | None) -> None:
    """Store a binding's manifest whole on its destination, or remove it with None.

    Raises RefusedRecordError, changing nothing, over one that can't be read; KeyError if there's no such binding;
    DisabledBindingError if it has no canonical candidate.
    """
    record = binding_operations.require_canonical_binding_record(binding_id)
    if manifest is None:
        manifests.remove_manifest(record.collection)
    else:
        manifests.write_manifest(record.collection, manifest)
    binding_operations.restore_missing_binding_index_entry(binding_id, record)


def set_manifest_entries(
    binding_id: BindingId,
    changed: Mapping[str, manifests.ManifestEntryChange],
    removed: Collection[str] = (),
    created: Mapping[str, bpy.types.ID] = MappingProxyType({}),
    *,
    published: manifests.Manifest | None = None,
) -> None:
    """Change some of a binding's manifest entries, writing only those.

    changed adds or replaces entries by entry key, and removed deletes them. created holds the datablocks the operation
    made, by the key of the entry naming each; a replaced entry not in it keeps its datablock (Manifest.updated). A
    binding with no manifest yet starts from an empty one, and an empty update writes nothing. published is the
    binding's manifest as the caller read it, unchanged since, so the update doesn't read it again; without it, the
    update reads it.

    Raises what set_manifest raises, and ValueError, TypeError, or KeyError (write_manifest_entries), changing nothing,
    over an update that makes no manifest.
    """
    record = binding_operations.require_canonical_binding_record(
        binding_id
    )  # raises as any update does, an empty one included
    if not changed and not removed:
        return
    if published is None:
        stored = manifests.read_manifest(record.collection)
        if isinstance(stored, RefusedRecord):
            raise RefusedRecordError(stored)
        published = manifests.Manifest({}) if stored is None else stored.record
    after = published.updated(changed, removed, created)
    manifests.write_manifest_entries(record.collection, after, changed.keys(), removed)
    binding_operations.restore_missing_binding_index_entry(binding_id, record)
