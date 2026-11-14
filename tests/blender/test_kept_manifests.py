"""Manifests kept between operations by their stored revision (proscenium.binding.runtime.kept_manifests).

Decodes are counted by wrapping proscenium.binding.persistence.manifests.read_manifest, which decodes the record; each
expected manifest is the one the test wrote or built.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from proscenium.binding.persistence import id_property_records, manifests
from proscenium.binding.persistence.id_property_records import LoadedRecord, RefusedRecord
from proscenium.binding.persistence.manifests import Manifest
from proscenium.binding.runtime import kept_manifests
from support import undo
from support.manifests import key, object_change, object_entry

if TYPE_CHECKING:
    from types import ModuleType

    import pytest


def _decodes(monkeypatch: pytest.MonkeyPatch) -> list[bpy.types.Collection]:
    """A list that gains the destination at each decode."""
    decoded: list[bpy.types.Collection] = []
    read = manifests.read_manifest

    def counted(destination: bpy.types.Collection) -> object:
        decoded.append(destination)
        return read(destination)

    monkeypatch.setattr(manifests, "read_manifest", counted)
    return decoded


def _destination() -> tuple[bpy.types.Collection, Manifest]:
    """A collection with a manifest of two objects, written through kept_manifests."""
    destination = bpy.data.collections.new("Destination")
    a, b = (bpy.data.objects.new(name, None) for name in ("A", "B"))
    manifest = Manifest({key("a"): object_entry(a, "/World/A"), key("b"): object_entry(b, "/World/B")})
    kept_manifests.write_manifest(destination, manifest)
    return destination, manifest


def _read(destination: bpy.types.Collection) -> Manifest:
    loaded = kept_manifests.read_manifest(destination)
    assert isinstance(loaded, LoadedRecord)
    return loaded.record


def test_reads_after_a_write_decode_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    # A write keeps what it wrote, so the reads after it return that manifest without decoding, until a write by entry
    # renews the revision and keeps its manifest in turn.
    decodes = _decodes(monkeypatch)
    destination, manifest = _destination()
    assert _read(destination) is manifest
    assert _read(destination) is manifest
    c = bpy.data.objects.new("C", None)
    after = manifest.updated({key("c"): object_change("/World/C")}, created={key("c"): c})
    kept_manifests.write_manifest_entries(destination, after, [key("c")], [])
    assert _read(destination) is after
    assert decodes == []


def test_a_removed_datablock_is_decoded_again(monkeypatch: pytest.MonkeyPatch) -> None:
    # Removing a datablock clears its pointer without a write, so the kept manifest, naming it, isn't returned: the
    # read decodes the record, whose entry names none, and keeps that.
    decodes = _decodes(monkeypatch)
    destination, _ = _destination()
    bpy.data.objects.remove(bpy.data.objects["A"])
    assert _read(destination).entries[key("a")].datablock is None
    assert _read(destination).entries[key("b")].datablock == bpy.data.objects["B"]
    assert decodes == [destination]


def test_a_manifest_without_a_revision_is_decoded_at_every_read(monkeypatch: pytest.MonkeyPatch) -> None:
    # As one stored before revisions: nothing tells a kept copy is current, so each read decodes it.
    decodes = _decodes(monkeypatch)
    destination, manifest = _destination()
    del destination[id_property_records.NAMESPACE][manifests.MANIFEST_KEY][id_property_records.REVISION_KEY]
    assert _read(destination) == manifest
    assert _read(destination) == manifest
    assert decodes == [destination, destination]


def test_a_refused_or_removed_manifest_is_not_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    # A manifest that can't be read is refused at every read; a removed one reads as none.
    decodes = _decodes(monkeypatch)
    destination, _ = _destination()
    destination[id_property_records.NAMESPACE][manifests.MANIFEST_KEY][id_property_records.VERSION_KEY] = 99
    kept_manifests.clear()  # as the load bringing a newer manifest does
    assert isinstance(kept_manifests.read_manifest(destination), RefusedRecord)
    assert isinstance(kept_manifests.read_manifest(destination), RefusedRecord)
    assert len(decodes) == 2
    del destination[id_property_records.NAMESPACE][manifests.MANIFEST_KEY]
    kept_manifests.write_manifest(destination, Manifest({}))
    kept_manifests.remove_manifest(destination)
    assert kept_manifests.read_manifest(destination) is None


def test_an_undo_restoring_a_removed_datablock_decodes_the_manifest(
    extension: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Removing A clears its pointer, so the manifest kept then names none; an undo restores A and its pointer under the
    # same revision. proscenium.addon clears what's kept after the undo, so the read after it decodes the record,
    # naming A again.
    del extension  # registered, so its handlers run
    undo.require_global_undo()
    decodes = _decodes(monkeypatch)
    destination, _ = _destination()
    undo.push("written")
    bpy.data.objects.remove(bpy.data.objects["A"])
    undo.push("removed")
    assert _read(destination).entries[key("a")].datablock is None
    undo.undo()
    restored = bpy.data.collections["Destination"]
    assert _read(restored).entries[key("a")].datablock == bpy.data.objects["A"]
    assert len(decodes) == 2
