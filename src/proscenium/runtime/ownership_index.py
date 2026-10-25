"""Ownership: whether each datablock is managed, from the claims on it (lifecycle.md#ownership-and-lifecycle).

ownership(datablock) answers through the ownership index, the claims on each datablock.

It's built from every destination's manifest in the bindings' state when first asked for, a tagged copy's included,
so content a copy names is ambiguous rather than one binding's. Each destination's claims are kept apart
(DestinationClaims), so a manifest write replaces only its own.

- Claims are keyed by datablock session_uid, not reference: a new datablock often takes a removed one's address, but
  never its session_uid, so a removed datablock's leftover claims are never found.
- A removed datablock costs a reread of the one manifest naming it, where Blender has cleared the entry, and that
  destination's claims are replaced.
- A manifest is checked whole before it's returned, since its entries name datablocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, NamedTuple

from ..persistence import manifests
from ..persistence.binding_records import DestinationTag
from ..persistence.manifests import Manifest
from ..persistence.records import Loaded, RefusedRecord, RefusedRecordError
from . import binding_configs, state
from .state import BindingRecord, StaleError, Unread

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    import bpy

    from ..core.binding_ids import BindingId
    from ..persistence.manifests import ManifestEntry
    from .state import DestinationRecords, State


@dataclass(frozen=True, slots=True)
class Claim:
    """A manifest entry naming a datablock: the evidence that a binding manages it (OWN-16).

    Each destination's manifest counts once, however many configurations name it, as a linked-copy scene's do, and a
    manifest that can't be read claims nothing. A claim doesn't survive an operator call or undo.
    """

    binding_id: BindingId  # the binding whose manifest holds the entry
    destination: bpy.types.Collection  # the collection holding that manifest; a binding's copies share binding_id
    resource_id: str  # the entry's key in that manifest


class OwnershipStatus(StrEnum):
    """What the claims on a datablock mean."""

    UNMANAGED = "unmanaged"  # no claims
    MANAGED = "managed"  # one: the binding whose manifest holds it manages it
    AMBIGUOUS = "ambiguous"  # two or more, from different manifests: reported, never claimed or deleted (OWN-09)


@dataclass(frozen=True, slots=True)
class Ownership:
    """Whether a datablock is managed, and the claims that say so."""

    claims: tuple[Claim, ...]  # in the order found

    @property
    def status(self) -> OwnershipStatus:
        """What the claims mean."""
        if not self.claims:
            return OwnershipStatus.UNMANAGED
        return OwnershipStatus.MANAGED if len(self.claims) == 1 else OwnershipStatus.AMBIGUOUS


@dataclass(slots=True)
class DestinationClaims:
    """What one destination's manifest adds to the ownership index, so a publication can change it alone."""

    claimant: BindingId  # the first binding found whose configuration names the destination, or else its tag's
    claims: dict[int, Claim]  # by datablock session_uid; a manifest names a datablock at most once
    entries: dict[str, int]  # resource identity -> its datablock's session_uid, for the entries naming one


@dataclass(slots=True)
class OwnershipIndex:
    """Every destination's manifest, indexed: the claims on each datablock (Claim), kept per destination."""

    # By datablock session_uid: one Claim, or a tuple of them for an ambiguous datablock, which is rare, so
    # the common case costs no list (88 bytes each, a quarter of the index).
    claims: dict[int, Claim | tuple[Claim, ...]]
    shares: dict[int, DestinationClaims]  # by destination session_uid


def ownership(datablock: bpy.types.ID) -> Ownership:
    """Whether datablock is managed, and by which binding: the claims on it in every manifest."""
    return Ownership(state.query(lambda s: _checked_claims(s, datablock)))


def manifest(binding_id: BindingId) -> Loaded[Manifest] | RefusedRecord | None:
    """A binding's manifest, read through its configuration's destination when first asked for.

    RefusedRecord if the configuration or the manifest can't be read; None if the binding has no destination (it was
    removed) or no manifest yet. Reads only that binding's manifest, not the ownership index. Raises KeyError if no
    binding has this identifier, and DisabledBindingError if it has no canonical candidate.
    """
    record = binding_configs.required_record(binding_id)
    current = state.current_state()
    if isinstance(record.config, RefusedRecord):
        return record.config
    if (destination := _destination_records(current, record)) is None:
        return None
    return _checked_manifest(current, binding_id, destination)


def set_manifest(binding_id: BindingId, manifest: Manifest) -> None:
    """Store a binding's manifest on its destination, replacing only that destination's share of ownership.

    Raises RefusedRecordError, changing nothing, over one that can't be read; KeyError if there's no such
    binding; DisabledBindingError if it has no canonical candidate; ValueError if it has no destination.
    """
    record = binding_configs.required_record(binding_id)
    current = state.current_state()
    destination = _destination(current, binding_id, record)
    manifests.write_manifest(destination.collection, manifest)
    _replace_manifest(current, binding_id, destination, Loaded(manifest, manifests.MANIFEST.version))
    binding_configs.restore_entry(binding_id, record)


def set_manifest_entries(
    binding_id: BindingId, changed: Mapping[str, ManifestEntry], removed: Collection[str] = ()
) -> None:
    """Change some of a binding's manifest entries, writing only those.

    changed adds or replaces entries by resource identity, and removed deletes them. A binding with no manifest yet
    starts from an empty one, and an empty update writes nothing. What it writes and indexes is what changes; in memory
    it also copies the manifest's entries and, with removals, scans their uses (Manifest.updated).

    Raises what set_manifest raises, and ValueError, TypeError, or KeyError (manifests.write_entries),
    changing nothing, over an update that makes no manifest.
    """
    # Read once: the checks, the record, and the index each go through it, so a one-shot iterable would leave
    # them disagreeing, and Manifest.updated tests it once per entry and per use.
    removed = frozenset(removed)
    if not changed and not removed:
        state.query(lambda s: _update_target(s, binding_id, indexed=False))  # raises as any update does
        return
    target = state.query(lambda s: _update_target(s, binding_id, indexed=True))
    index, share, destination = target.current.ownership, target.share, target.destination
    assert index is not None and share is not None
    after = target.before.updated(changed, removed, lambda uid: c.resource_id if (c := share.claims.get(uid)) else None)
    manifests.write_entries(destination.collection, after, changed.keys(), removed)
    destination.manifest = Loaded(after, manifests.MANIFEST.version)
    for resource_id in [*changed, *removed]:
        _remove_claim(index, share, resource_id)
    for resource_id in changed:
        if (datablock := after.entries[resource_id].datablock) is not None:
            _add_claim(index, share, datablock, Claim(share.claimant, destination.collection, resource_id))
    binding_configs.restore_entry(binding_id, target.record)


class _UpdateTarget(NamedTuple):
    """What set_manifest_entries changes, all from one state."""

    current: State
    record: BindingRecord  # the binding's canonical record
    destination: DestinationRecords
    before: Manifest  # its stored manifest, or an empty one if it has none yet
    share: DestinationClaims | None  # the destination's claims in the ownership index, if indexed


def _update_target(current: State, binding_id: BindingId, *, indexed: bool) -> _UpdateTarget:
    """The binding's record, destination, and manifest, and with indexed its claims; raises as set_manifest does.

    A question for state.query, so all of them come from the same state: building the ownership index can find a
    removed destination, which rebuilds the state and asks again.
    """
    record = binding_configs.required_record_in(current, binding_id)
    destination = _destination(current, binding_id, record)
    # Unchecked, which would cost the manifest: an entry naming a removed datablock is carried into the result,
    # whose next check rereads it, and its claim, under a session_uid no other datablock gets, stays unfound.
    stored = _manifest_of(destination)
    if isinstance(stored, RefusedRecord):
        raise RefusedRecordError(stored)
    share = _ownership(current).shares[destination.collection.session_uid] if indexed else None
    before = Manifest({}) if stored is None else stored.record
    return _UpdateTarget(current, record, destination, before, share)


def _destination(current: State, binding_id: BindingId, record: BindingRecord) -> DestinationRecords:
    """The records on the destination of a binding's record; ValueError if it has none to hold a manifest."""
    if isinstance(record.config, RefusedRecord) or (destination := _destination_records(current, record)) is None:
        raise ValueError(f"binding {binding_id} has no destination to hold a manifest")
    return destination


def _destination_records(current: State, record: BindingRecord) -> DestinationRecords | None:
    """The records on the destination a readable binding record names, or None if it names none."""
    if isinstance(record.config, RefusedRecord) or record.config.destination is None:
        return None
    if (destination := current.destinations.get(record.config.destination.session_uid)) is None:
        raise StaleError  # a destination the state wasn't built with
    return destination


def _manifest_of(destination: DestinationRecords) -> Loaded[Manifest] | RefusedRecord | None:
    """The destination's manifest, read the first time."""
    if isinstance(destination.manifest, Unread):
        destination.manifest = manifests.read_manifest(destination.collection)
    return destination.manifest


def _checked_manifest(
    current: State, binding_id: BindingId, destination: DestinationRecords
) -> Loaded[Manifest] | RefusedRecord | None:
    """The destination's manifest, reread if a datablock it names was removed; Blender cleared that entry's pointer."""
    manifest = _manifest_of(destination)
    if isinstance(manifest, Loaded) and not all(
        e.datablock is None or state.alive(e.datablock) for e in manifest.record.entries.values()
    ):
        manifest = _reread(current, binding_id, destination)
    return manifest


def _reread(
    current: State, binding_id: BindingId, destination: DestinationRecords
) -> Loaded[Manifest] | RefusedRecord | None:
    """Reread a destination's manifest after a datablock it names was removed, replacing its share alone."""
    manifest = manifests.read_manifest(destination.collection)
    _replace_manifest(current, binding_id, destination, manifest)
    return manifest


def _replace_manifest(
    current: State,
    binding_id: BindingId,
    destination: DestinationRecords,
    manifest: Loaded[Manifest] | RefusedRecord | None,
) -> None:
    """Hold the destination's new manifest, and replace its share of ownership.

    The share keeps its claimant (binding_id's, if it has no share yet).
    """
    destination.manifest = manifest
    if (index := current.ownership) is not None:
        uid = destination.collection.session_uid
        share = index.shares.get(uid)
        _remove_share(index, uid)
        _add_share(index, binding_id if share is None else share.claimant, destination.collection, manifest)


def _ownership(current: State) -> OwnershipIndex:
    """The ownership index, built from every destination's manifest if it isn't.

    Each destination counts once, though several configurations can name it, with the first binding
    found whose configuration names it as the claimant; a tagged collection no record names claims
    for the binding its tag names.
    """
    if current.ownership is None:
        index = OwnershipIndex({}, {})
        for uid, claimant in _claimants(current).items():
            destination = current.destinations[uid]
            if not state.alive(destination.collection):
                raise StaleError  # removed since the state was built
            _add_share(index, claimant, destination.collection, _checked_manifest(current, claimant, destination))
        current.ownership = index
    return current.ownership


def _claimants(current: State) -> dict[int, BindingId]:
    """By destination session_uid, the binding each destination's claims name, in the order found."""
    claimants: dict[int, BindingId] = {}
    for binding_id, identity in current.identities.items():
        for record in identity.records:
            if isinstance(record.config, RefusedRecord) or (collection := record.config.destination) is None:
                continue
            if not state.alive(collection):
                raise StaleError  # removed since the state was built: Blender cleared the configurations' pointers
            claimants.setdefault(collection.session_uid, binding_id)
    for uid, destination in current.destinations.items():  # tagged collections no record names
        if isinstance(destination.tag, DestinationTag):
            claimants.setdefault(uid, destination.tag.binding_id)
    return claimants


def _add_share(
    index: OwnershipIndex,
    claimant: BindingId,
    destination: bpy.types.Collection,
    manifest: Loaded[Manifest] | RefusedRecord | None,
) -> None:
    uid = destination.session_uid
    share = DestinationClaims(claimant, {}, {})
    if isinstance(manifest, Loaded):  # one that can't be read claims nothing until it is repaired
        for resource_id, entry in manifest.record.entries.items():
            if entry.datablock is not None:
                _add_claim(index, share, entry.datablock, Claim(claimant, destination, resource_id))
    index.shares[uid] = share


def _remove_share(index: OwnershipIndex, uid: int) -> None:
    if (share := index.shares.pop(uid, None)) is None:
        return
    for resource_id in list(share.entries):
        _remove_claim(index, share, resource_id)


def _add_claim(index: OwnershipIndex, share: DestinationClaims, datablock: bpy.types.ID, claim: Claim) -> None:
    datablock_uid = datablock.session_uid
    if (existing := index.claims.get(datablock_uid)) is None:
        index.claims[datablock_uid] = claim
    else:
        index.claims[datablock_uid] = (*_as_tuple(existing), claim)
    share.claims[datablock_uid] = claim
    share.entries[claim.resource_id] = datablock_uid


def _remove_claim(index: OwnershipIndex, share: DestinationClaims, resource_id: str) -> None:
    """Take out the claim of the share's entry for resource_id, if it names a datablock."""
    if (datablock_uid := share.entries.pop(resource_id, None)) is None:
        return
    claim = share.claims.pop(datablock_uid)
    remaining = tuple(c for c in _as_tuple(index.claims[datablock_uid]) if c is not claim)
    if not remaining:
        del index.claims[datablock_uid]
    else:
        index.claims[datablock_uid] = remaining[0] if len(remaining) == 1 else remaining


def _checked_claims(current: State, datablock: bpy.types.ID) -> tuple[Claim, ...]:
    indexed = _ownership(current).claims.get(datablock.session_uid)
    claims = () if indexed is None else _as_tuple(indexed)
    if not all(state.alive(claim.destination) for claim in claims):
        raise StaleError
    return claims


def _as_tuple(claims: Claim | tuple[Claim, ...]) -> tuple[Claim, ...]:
    return claims if isinstance(claims, tuple) else (claims,)
