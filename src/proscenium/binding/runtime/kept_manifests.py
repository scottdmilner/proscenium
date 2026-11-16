"""Manifests kept between operations by their stored revision, so reading an unchanged one decodes nothing.

Decoding a manifest builds an entry for each managed resource: 52 ms for ALab's 13,358 entries, most of an unchanged
synchronization's time (runtime-record.md#the-products-synchronizations-m7-phase-g). Each record write stores a new
revision (id_property_records.REVISION_KEY), so a destination's manifest is kept with the revision it was read or
written at, and a read whose stored revision is the kept one returns it, once every datablock it names is checked
alive: removing a datablock clears its pointer in the record without a write, so a kept manifest naming a removed one
is decoded again. A manifest stored before revisions is decoded at every read until it is next written.

Beside a kept manifest, the grouping of its copies' partitions a refresh decides from
(copy_partitions.PublishedPartitions): built from every entry the first time it's asked for, then kept in step
with each write by entry, which gives it only the entries it changed and removed. A whole write keeps none, to be built
again when next asked for.

Every manifest read and write goes through here, so a write keeps what it wrote. A manifest names datablocks, which an
undo, a redo, or a file load may free or restore, so proscenium.addon clears what's kept after each (clear).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..persistence import id_property_records, manifests
from ..persistence.id_property_records import LoadedRecord, RefusedRecord
from . import copy_partitions

if TYPE_CHECKING:
    from collections.abc import Collection

    import bpy


@dataclass(frozen=True, slots=True)
class _KeptManifest:
    revision: str
    loaded: LoadedRecord[manifests.Manifest]
    # Its copies' partitions, once asked for; each write by entry changes them in place.
    partitions: copy_partitions.PublishedPartitions | None = None


class _KeptManifestsState:
    kept_by_destination: dict[int, _KeptManifest] = {}  # noqa: RUF012 - by the destination's session_uid


def read_manifest(destination: bpy.types.Collection) -> LoadedRecord[manifests.Manifest] | RefusedRecord | None:
    """The destination's manifest, kept or decoded: why it can't be read, or None if it has none."""
    revision = manifests.manifest_revision(destination)
    kept = _KeptManifestsState.kept_by_destination.get(destination.session_uid)
    if kept is not None and revision is not None and kept.revision == revision and _all_alive(kept.loaded.record):
        return kept.loaded
    loaded = manifests.read_manifest(destination)
    _keep(destination, revision, loaded)
    return loaded


def published_partitions(
    destination: bpy.types.Collection, manifest: manifests.Manifest
) -> copy_partitions.PublishedPartitions:
    """The partitions of manifest's copies, kept if manifest is the destination's kept one, else built.

    The destination's next write by entry changes kept partitions in place, so a caller uses them only until then.
    """
    kept = _KeptManifestsState.kept_by_destination.get(destination.session_uid)
    if kept is None or kept.loaded.record is not manifest:
        return copy_partitions.PublishedPartitions(manifest)
    if kept.partitions is None:
        kept = _KeptManifest(kept.revision, kept.loaded, copy_partitions.PublishedPartitions(manifest))
        _KeptManifestsState.kept_by_destination[destination.session_uid] = kept
    assert kept.partitions is not None
    return kept.partitions


def write_manifest(destination: bpy.types.Collection, manifest: manifests.Manifest) -> LoadedRecord[manifests.Manifest]:
    """Store the destination's manifest whole and keep it (manifests.write_manifest)."""
    written = manifests.write_manifest(destination, manifest)
    _keep(destination, manifests.manifest_revision(destination), written)
    return written


def write_manifest_entries(
    destination: bpy.types.Collection, manifest: manifests.Manifest, changed: Collection[str], removed: Collection[str]
) -> LoadedRecord[manifests.Manifest]:
    """Store manifest by its changed and removed entries and keep it (manifests.write_manifest_entries).

    Kept partitions of the manifest the write replaces take its changed and removed entries.
    """
    kept = _KeptManifestsState.kept_by_destination.get(destination.session_uid)
    current = kept is not None and kept.revision == manifests.manifest_revision(destination)
    partitions = kept.partitions if current and kept is not None else None
    written = manifests.write_manifest_entries(destination, manifest, changed, removed)
    if partitions is not None:
        partitions.replace_entries(manifest, changed, removed)
    _keep(destination, manifests.manifest_revision(destination), written, partitions)
    return written


def remove_manifest(destination: bpy.types.Collection) -> None:
    """Remove the destination's manifest, if it has one, keeping none (manifests.remove_manifest)."""
    manifests.remove_manifest(destination)
    _KeptManifestsState.kept_by_destination.pop(destination.session_uid, None)


def clear() -> None:
    """Keep no manifest, as after an undo, a redo, or a file load, which may free or restore what they name."""
    _KeptManifestsState.kept_by_destination.clear()


def _keep(
    destination: bpy.types.Collection,
    revision: str | None,
    loaded: LoadedRecord[manifests.Manifest] | RefusedRecord | None,
    partitions: copy_partitions.PublishedPartitions | None = None,
) -> None:
    if revision is not None and isinstance(loaded, LoadedRecord):
        kept = _KeptManifest(revision, loaded, partitions)
        _KeptManifestsState.kept_by_destination[destination.session_uid] = kept
    else:
        _KeptManifestsState.kept_by_destination.pop(destination.session_uid, None)


def _all_alive(manifest: manifests.Manifest) -> bool:
    """Whether every datablock the manifest names still exists."""
    alive = id_property_records.alive
    return all(entry.datablock is None or alive(entry.datablock) for entry in manifest.entries.values())
