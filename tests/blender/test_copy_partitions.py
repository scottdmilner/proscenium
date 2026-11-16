"""A published manifest's copies' partitions, kept in step with writes by entry (binding.runtime.copy_partitions).

Each write is a manifest update as ownership.set_manifest_entries makes one (Manifest.updated); after each, the kept
partitions must equal partitions grouped from the whole manifest written, copy by copy, with the same unused shared
datablocks.
"""

from __future__ import annotations

import bpy

from proscenium.binding.persistence.manifests import Manifest, ManifestEntryChange, RepresentationRole
from proscenium.binding.runtime.copy_partitions import CopyPartition, PublishedPartitions
from support.manifests import key, object_change

SOURCES = ("/World/A", "/World/B", "/World/C")


def _change(
    role: RepresentationRole, source: str | None, place: int | None = 0, uses: tuple[str, ...] = ()
) -> ManifestEntryChange:
    paths = [source] if source is not None else ["/"]
    return ManifestEntryChange(paths, role, [key(u) for u in uses], place)


def _snapshot(
    partitions: PublishedPartitions, manifest: Manifest
) -> tuple[dict[str, CopyPartition | None], list[set[str]]]:
    """Each source's partition, and the unused shared entries with nothing replaced and with each copy's replaced."""
    by_source = {source: partitions.partition(source) for source in (*SOURCES, "/World/D")}
    replaced_sets = [
        set(),
        *({k for k, e in manifest.entries.items() if e.source_entity_paths[0] == s} for s in SOURCES),
    ]
    return by_source, [partitions.unused_shared(replaced) for replaced in replaced_sets]


def test_kept_partitions_match_a_whole_manifests_through_writes_by_entry() -> None:
    # A copy added and removed, a resource gone, an action added and removed, a shear parent and a second object, and a
    # shared datablock sampled by two copies, losing one user and then the other.
    role = RepresentationRole

    def made(name: str) -> bpy.types.ID:
        return bpy.data.objects.new(name, None)

    manifest = Manifest({})
    kept = PublishedPartitions(manifest)
    writes: list[tuple[dict[str, ManifestEntryChange], list[str]]] = [
        ({"a": object_change(SOURCES[0]), "b": object_change(SOURCES[1]), "c": object_change(SOURCES[2])}, []),
        ({"a action": _change(role.ACTION, SOURCES[0])}, []),
        ({"b parent": _change(role.SHEAR_PARENT, SOURCES[1]), "c 1": _change(role.OBJECT, SOURCES[2], place=1)}, []),
        ({"frames": _change(role.NODE_GROUP, None, None)}, []),
        ({"a samples": _change(role.BOUNDS_MESH, SOURCES[0], uses=("frames",))}, []),
        ({"b samples": _change(role.BOUNDS_MESH, SOURCES[1], uses=("frames",))}, []),
        ({}, ["a samples"]),
        ({}, ["b samples", "frames", "a action"]),
        ({"d": object_change("/World/D")}, ["c", "c 1"]),
    ]
    for changes, removed in writes:
        changed = {key(name): change for name, change in changes.items()}
        created = {k: made(name) for name, k in ((n, key(n)) for n in changes)}
        manifest = manifest.updated(changed, [key(n) for n in removed], created)
        kept.replace_entries(manifest, changed, [key(n) for n in removed])
        assert _snapshot(kept, manifest) == _snapshot(PublishedPartitions(manifest), manifest), (changes, removed)
