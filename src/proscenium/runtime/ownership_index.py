"""The ownership index: the claims on each datablock (lifecycle.md#ownership-and-lifecycle).

Ownership counts every candidate's manifest, a tagged collection's that no record names included
(Claim), so copied content is ambiguous rather than any one binding's. The index is built from the
manifests in the bindings' state (proscenium.runtime.state) when first asked for, and a manifest write
replaces only its destination's claims.

A removed datablock costs a reread of the one manifest that names it, where Blender has cleared its
entry, and that destination's claims are replaced. A manifest is checked whole when it's returned,
since its entries name datablocks. Claims are keyed by each datablock's session_uid, which no other
datablock in the session gets and an undo re-read keeps, not by its reference: a new datablock often
takes a removed one's address, and a removed one's claims, left until its destination's claims are
next replaced, are never found.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..persistence import manifests
from ..persistence.manifests import Manifest
from ..persistence.records import Loaded, RefusedRecord, RefusedRecordError
from . import binding_configs, state
from .copy_detection import CopiedBinding
from .state import Candidate, StaleError, Unread

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    import bpy

    from ..core.binding_ids import BindingId
    from ..persistence.manifests import ManifestEntry
    from .state import State


@dataclass(frozen=True, slots=True)
class Claim:
    """A manifest entry naming a datablock: the evidence that a binding manages it (OWN-16).

    A manifest names a datablock at most once, so each claim on a datablock comes from a different
    manifest. One claim means the datablock is managed by that binding; two or more, that it is
    ambiguous: it is reported, never automatically claimed or deleted (OWN-09); none, that it is
    unmanaged. That judgment needs every manifest that could name the datablock, so the ownership
    index indexes every binding's. Each destination's manifest counts once, though several
    configurations can name it, as a linked-copy scene's do. A manifest that can't be read claims
    nothing, so its content has no ownership evidence until it is repaired. A binding's copies share
    its identity, so the destination says which manifest a claim comes from. Like the datablocks it
    sits beside, it doesn't survive an operator call or undo.
    """

    binding_id: BindingId  # the binding whose manifest holds the entry
    destination: bpy.types.Collection  # the collection holding that manifest
    resource_id: str  # the entry's key in that manifest


@dataclass(slots=True)
class DestinationClaims:
    """What one destination's manifest adds to the ownership index, so a publication can change it alone."""

    claimant: BindingId  # the binding its claims name: the first found whose configuration names the destination
    claims: dict[int, Claim]  # by datablock session_uid; a manifest names a datablock at most once
    entries: dict[str, int]  # resource identity -> its datablock's session_uid, for the entries naming one


@dataclass(slots=True)
class OwnershipIndex:
    """Every candidate's manifest, indexed: the claims on each datablock (Claim), kept per destination."""

    # By datablock session_uid: one Claim, or a tuple of them for an ambiguous datablock, which is rare, so
    # the common case costs no list (88 bytes each, a quarter of the index).
    claims: dict[int, Claim | tuple[Claim, ...]]
    unreadable: dict[int, RefusedRecord]  # by destination session_uid: manifests that can't be read
    shares: dict[int, DestinationClaims]  # by destination session_uid


def manifest(binding_id: BindingId) -> Loaded[Manifest] | RefusedRecord | CopiedBinding | None:
    """A binding's manifest, read through its configuration's destination when first asked for.

    RefusedRecord if the configuration or the manifest can't be read; the binding's report if it has no
    canonical candidate; None if the binding has no destination (it was removed) or no manifest yet. Raises
    KeyError if no binding has this identifier.
    """
    if isinstance(candidate := binding_configs.existing(binding_id), CopiedBinding):
        return candidate
    return _checked_manifest(state.current_state(), binding_id, candidate)


def set_manifest(binding_id: BindingId, manifest: Manifest) -> None:
    """Store a binding's manifest on its destination, replacing only that destination's share of ownership.

    Raises RefusedRecordError, changing nothing, over one that can't be read; KeyError if there's no such
    binding; BindingDisabledError if it has no canonical candidate; ValueError if it has no destination.
    """
    candidate = binding_configs.writable(binding_id)
    destination = _destination(binding_id, candidate)
    manifests.write_manifest(destination, manifest)
    _replace_manifest(state.current_state(), binding_id, destination, Loaded(manifest, manifests.MANIFEST.version))
    binding_configs.restore_entry(binding_id, candidate)


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
    candidate, destination, stored = _to_update(binding_id)
    if not changed and not removed:
        return
    # Built first through query(), which rebuilds the state if any destination was removed; then looked up again.
    state.query(_ownership)
    candidate, destination, stored = _to_update(binding_id)
    current = state.current_state()
    index = current.ownership
    assert index is not None
    share = index.shares[destination.session_uid]
    before = Manifest({}) if stored is None else stored.record
    after = before.updated(changed, removed, lambda uid: c.resource_id if (c := share.claims.get(uid)) else None)
    manifests.write_entries(destination, after, changed.keys(), removed)
    _cache_manifest(current, destination, Loaded(after, manifests.MANIFEST.version))
    keys = [*changed, *removed]
    for resource_id in keys:
        _remove_claim(index, share, resource_id)
    for resource_id in changed:
        if (datablock := after.entries[resource_id].datablock) is not None:
            _add_claim(index, share, datablock, Claim(share.claimant, destination, resource_id))
    binding_configs.restore_entry(binding_id, candidate)


def claims_on(datablock: bpy.types.ID) -> list[Claim]:
    """The claims on datablock; none if it is unmanaged (Claim says what they mean)."""
    return state.query(lambda s: _checked_claims(s, datablock))


def resource(binding_id: BindingId, resource_id: str) -> bpy.types.ID | CopiedBinding | None:
    """The datablock of a binding's resource, as its manifest names it.

    The binding's report if it has no canonical candidate; None if the manifest names none, or the binding has no
    destination or manifest. Reads only that binding's manifest, not the ownership index.
    """
    return state.query(lambda s: _checked_resource(s, binding_id, resource_id))


def unreadable_manifests() -> list[RefusedRecord]:
    """Every manifest that can't be read, once per destination."""
    return state.query(lambda s: list(_ownership(s).unreadable.values()))


def _to_update(binding_id: BindingId) -> tuple[Candidate, bpy.types.Collection, Loaded[Manifest] | None]:
    """The binding, its destination, and its manifest, for set_manifest_entries. Raises as set_manifest_entries does."""
    candidate = binding_configs.writable(binding_id)
    destination = _destination(binding_id, candidate)
    # Unchecked, which would cost the manifest: an entry naming a removed datablock is carried into the result,
    # whose next check rereads it, and its claim, under a session_uid no other datablock gets, stays unfound.
    stored = _manifest_of(candidate)
    if isinstance(stored, RefusedRecord):
        raise RefusedRecordError(stored)
    return candidate, destination, stored


def _destination(binding_id: BindingId, candidate: Candidate) -> bpy.types.Collection:
    if isinstance(candidate.config, RefusedRecord) or candidate.config.destination is None:
        raise ValueError(f"binding {binding_id} has no destination to hold a manifest")
    return candidate.config.destination


def _manifest_of(candidate: Candidate) -> Loaded[Manifest] | RefusedRecord | None:
    """The candidate's manifest, read through its destination the first time."""
    if isinstance(candidate.config, RefusedRecord):
        return candidate.config
    if isinstance(candidate.manifest, Unread):
        destination = candidate.config.destination
        candidate.manifest = None if destination is None else manifests.read_manifest(destination)
    return candidate.manifest


def _checked_manifest(
    current: State, binding_id: BindingId, candidate: Candidate
) -> Loaded[Manifest] | RefusedRecord | None:
    """The candidate's manifest, reread if a datablock it names was removed; Blender cleared that entry's pointer."""
    manifest = _manifest_of(candidate)
    if isinstance(manifest, Loaded) and not all(
        e.datablock is None or state.alive(e.datablock) for e in manifest.record.entries.values()
    ):
        assert not isinstance(candidate.config, RefusedRecord) and candidate.config.destination is not None
        manifest = _reread(current, binding_id, candidate.config.destination)
    return manifest


def _reread(
    current: State, binding_id: BindingId, destination: bpy.types.Collection
) -> Loaded[Manifest] | RefusedRecord | None:
    """Reread a destination's manifest after a datablock it names was removed, replacing its share alone."""
    manifest = manifests.read_manifest(destination)
    _replace_manifest(current, binding_id, destination, manifest)
    return manifest


def _replace_manifest(
    current: State,
    binding_id: BindingId,
    destination: bpy.types.Collection,
    manifest: Loaded[Manifest] | RefusedRecord | None,
) -> None:
    """Give the manifest to every configuration naming the destination, and replace its share of ownership.

    The share keeps its claimant (binding_id's, if it has no share yet).
    """
    _cache_manifest(current, destination, manifest)
    if (index := current.ownership) is not None:
        uid = destination.session_uid
        share = index.shares.get(uid)
        _remove_share(index, uid)
        _add_share(index, binding_id if share is None else share.claimant, destination, manifest)


def _cache_manifest(
    current: State, destination: bpy.types.Collection, manifest: Loaded[Manifest] | RefusedRecord | None
) -> None:
    """Give the manifest to every configuration naming the destination, as a linked copy's does."""
    for _, candidate in current.by_destination.get(destination.session_uid, ()):
        candidate.manifest = manifest


def _ownership(current: State) -> OwnershipIndex:
    """The ownership index, built from every candidate's manifest if it isn't.

    Each destination counts once, though several configurations can name it, with the first binding
    found whose configuration names it as the claimant; a tagged collection no record names claims
    for the binding its tag names.
    """
    if current.ownership is None:
        index = OwnershipIndex({}, {}, {})
        for naming in current.by_destination.values():
            binding_id, candidate = naming[0]
            assert not isinstance(candidate.config, RefusedRecord) and candidate.config.destination is not None
            if not state.alive(candidate.config.destination):
                raise StaleError  # removed since the state was built: Blender cleared the configurations' pointers
            destination = candidate.config.destination
            _add_share(index, binding_id, destination, _checked_manifest(current, binding_id, candidate))
        for binding_id, identity in current.identities.items():  # tagged collections no record names
            for copy in identity.tagged_copies:
                if not state.alive(copy):
                    raise StaleError
                _add_share(index, binding_id, copy, manifests.read_manifest(copy))
        current.ownership = index
    return current.ownership


def _add_share(
    index: OwnershipIndex,
    claimant: BindingId,
    destination: bpy.types.Collection,
    manifest: Loaded[Manifest] | RefusedRecord | None,
) -> None:
    uid = destination.session_uid
    share = DestinationClaims(claimant, {}, {})
    if isinstance(manifest, RefusedRecord):
        index.unreadable[uid] = manifest  # claims nothing until it is repaired
    elif manifest is not None:
        for resource_id, entry in manifest.record.entries.items():
            if entry.datablock is not None:
                _add_claim(index, share, entry.datablock, Claim(claimant, destination, resource_id))
    index.shares[uid] = share


def _remove_share(index: OwnershipIndex, uid: int) -> None:
    if (share := index.shares.pop(uid, None)) is None:
        return
    for resource_id in list(share.entries):
        _remove_claim(index, share, resource_id)
    index.unreadable.pop(uid, None)


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


def _checked_claims(current: State, datablock: bpy.types.ID) -> list[Claim]:
    indexed = _ownership(current).claims.get(datablock.session_uid)
    claims = [] if indexed is None else list(_as_tuple(indexed))
    if not all(state.alive(claim.destination) for claim in claims):
        raise StaleError
    return claims


def _as_tuple(claims: Claim | tuple[Claim, ...]) -> tuple[Claim, ...]:
    return claims if isinstance(claims, tuple) else (claims,)


def _checked_resource(current: State, binding_id: BindingId, resource_id: str) -> bpy.types.ID | CopiedBinding | None:
    """Through the manifest of the binding's canonical candidate, checked as every lookup by identity is."""
    if not isinstance(candidate := binding_configs.canonical(current, binding_id), Candidate):
        return candidate
    datablock = _datablock_of(_manifest_of(candidate), resource_id)
    if datablock is not None and not state.alive(datablock):
        # Removed: its manifest is reread, where Blender has cleared the entry, and its share replaced.
        assert not isinstance(candidate.config, RefusedRecord) and candidate.config.destination is not None
        datablock = _datablock_of(_reread(current, binding_id, candidate.config.destination), resource_id)
        if datablock is not None and not state.alive(datablock):
            raise StaleError
    return datablock


def _datablock_of(manifest: Loaded[Manifest] | RefusedRecord | None, resource_id: str) -> bpy.types.ID | None:
    entry = manifest.record.entries.get(resource_id) if isinstance(manifest, Loaded) else None
    return None if entry is None else entry.datablock
