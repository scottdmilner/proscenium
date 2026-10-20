"""Ownership metadata: the manifest, and what it makes managed (lifecycle.md#ownership-and-lifecycle; OWN-01, OWN-16).

Bindings come from the synchronization API on a fresh process state per test; their managed
content is made here, as M5's application layer will make it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import source_access
from proscenium import ownership, synchronization
from proscenium.ownership import Claim, Manifest, ManifestEntry
from proscenium.records import NAMESPACE, VERSION_KEY, Loaded, RecordRefused, Refusal, Refused
from proscenium.synchronization import BindingHandle, Synchronization
from support.blend import save_and_reopen

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def sync(monkeypatch: pytest.MonkeyPatch) -> Iterator[Synchronization]:
    fresh = Synchronization()
    monkeypatch.setattr(synchronization, "SYNCHRONIZATION", fresh)
    yield fresh


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _managed(sync: Synchronization, tmp_path: Path, name: str = "Shot") -> tuple[BindingHandle, Manifest]:
    """A binding whose destination holds two managed objects sharing a managed mesh, and its manifest."""
    with source_access.binding_state(tmp_path / name) as scene:
        handle = sync.create_file_binding(_scene(), scene.root, name=name)
    destination = bpy.data.collections[name]
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    objects = [bpy.data.objects.new(f"{name}{i}", mesh) for i in range(2)]
    for obj in objects:
        destination.objects.link(obj)
    entries = {
        "mesh": ManifestEntry(mesh, ["/World/Ref", "/World/Pay"], "shared geometry", []),
        "a": ManifestEntry(objects[0], ["/World/Ref"], "prim", ["mesh"]),
        "b": ManifestEntry(objects[1], ["/World/Pay"], "prim", ["mesh"]),
    }
    manifest = Manifest(entries)
    ownership.write_manifest(destination, manifest)
    return handle, manifest


def _claims() -> dict[bpy.types.ID, list[Claim]]:
    found, unreadable = ownership.claims()
    assert unreadable == []
    return found


def test_a_manifest_survives_save_and_reopen(sync: Synchronization, tmp_path: Path) -> None:
    # OWN-01: identity (the key), datablock, coverage, role, and uses, each its own field.
    _managed(sync, tmp_path)
    save_and_reopen(tmp_path / "manifest.blend")
    mesh, a, b = bpy.data.meshes["ShotMesh"], bpy.data.objects["Shot0"], bpy.data.objects["Shot1"]
    expected = Manifest(
        {
            "mesh": ManifestEntry(mesh, ["/World/Ref", "/World/Pay"], "shared geometry", []),
            "a": ManifestEntry(a, ["/World/Ref"], "prim", ["mesh"]),
            "b": ManifestEntry(b, ["/World/Pay"], "prim", ["mesh"]),
        }
    )
    assert ownership.read_manifest(bpy.data.collections["Shot"]) == Loaded(expected, 1)


def test_nothing_is_stored_on_the_managed_datablocks(sync: Synchronization, tmp_path: Path) -> None:
    _managed(sync, tmp_path)
    for datablock in (bpy.data.meshes["ShotMesh"], bpy.data.objects["Shot0"]):
        assert NAMESPACE not in datablock


def test_the_manifest_names_what_is_managed(sync: Synchronization, tmp_path: Path) -> None:
    # OWN-16: one claim each, from the binding whose manifest names it.
    handle, _ = _managed(sync, tmp_path)
    shot = bpy.data.collections["Shot"]
    assert _claims() == {
        bpy.data.meshes["ShotMesh"]: [Claim(handle.binding_id, shot, "mesh")],
        bpy.data.objects["Shot0"]: [Claim(handle.binding_id, shot, "a")],
        bpy.data.objects["Shot1"]: [Claim(handle.binding_id, shot, "b")],
    }


def test_a_duplicate_of_managed_content_is_unmanaged(sync: Synchronization, tmp_path: Path) -> None:
    # OWN-16: Object > Duplicate copies the object, and no manifest names the copy.
    _managed(sync, tmp_path)
    view_layer = bpy.context.view_layer
    assert view_layer is not None
    original = bpy.data.objects["Shot0"]
    original.select_set(True)
    view_layer.objects.active = original
    bpy.ops.object.duplicate()
    [copy] = [o for o in bpy.data.objects if o.name.startswith("Shot0.")]
    found = _claims()
    assert copy not in found
    assert original in found


def test_content_two_manifests_name_is_ambiguous(sync: Synchronization, tmp_path: Path) -> None:
    first, _ = _managed(sync, tmp_path, "First")
    second, _ = _managed(sync, tmp_path, "Second")
    shared = bpy.data.objects["First0"]
    manifest = ownership.read_manifest(bpy.data.collections["Second"])
    assert isinstance(manifest, Loaded)
    entries = manifest.record.entries | {"stolen": ManifestEntry(shared, ["/World/Ref"], "prim", [])}
    ownership.write_manifest(bpy.data.collections["Second"], Manifest(entries))
    first_claim = Claim(first.binding_id, bpy.data.collections["First"], "a")
    assert _claims()[shared] == [first_claim, Claim(second.binding_id, bpy.data.collections["Second"], "stolen")]


def test_a_manifest_names_a_datablock_once(sync: Synchronization, tmp_path: Path) -> None:
    # So two claims on a datablock always come from two manifests.
    _, manifest = _managed(sync, tmp_path)
    twice = manifest.entries["a"]
    with pytest.raises(ValueError, match="two entries name one datablock"):
        Manifest(manifest.entries | {"again": twice})


def test_after_a_full_copy_each_copy_is_managed_by_its_own_manifest(sync: Synchronization, tmp_path: Path) -> None:
    # The copied manifest's pointers are rewritten to the copied datablocks (runtime-record.md#copy-routes-m3).
    _managed(sync, tmp_path)
    window = bpy.context.window
    assert window is not None
    window.scene = _scene()
    bpy.ops.scene.new(type="FULL_COPY")
    found = _claims()
    for collection in (bpy.data.collections["Shot"], bpy.data.collections["Shot.001"]):
        for obj in collection.objects:
            [claim] = found[obj]
            assert claim.destination == collection  # the copies share the binding identity, not the manifest


def test_a_linked_copy_scene_shares_one_manifest(sync: Synchronization, tmp_path: Path) -> None:
    # Both scenes' configurations point at the one destination, which is read once: one claim each.
    handle, _ = _managed(sync, tmp_path)
    window = bpy.context.window
    assert window is not None
    window.scene = _scene()
    bpy.ops.scene.new(type="LINK_COPY")
    assert len(bpy.data.scenes) == 2
    shot = bpy.data.collections["Shot"]
    found = _claims()
    assert {obj: claims for obj, claims in found.items() if obj in set(shot.objects)} == {
        bpy.data.objects["Shot0"]: [Claim(handle.binding_id, shot, "a")],
        bpy.data.objects["Shot1"]: [Claim(handle.binding_id, shot, "b")],
    }


def test_deleting_in_the_interface_keeps_the_content_claimed(sync: Synchronization, tmp_path: Path) -> None:
    # The manifest's pointer is a user, so Object > Delete unlinks the object but leaves it in the file,
    # still named, until a refresh or cleanup finds it linked nowhere.
    _managed(sync, tmp_path)
    obj = bpy.data.objects["Shot0"]
    users = obj.users
    view_layer = bpy.context.view_layer
    assert view_layer is not None
    obj.select_set(True)
    view_layer.objects.active = obj
    bpy.ops.object.delete()
    obj = bpy.data.objects["Shot0"]
    assert obj.users == users - 1  # the destination's link is gone; the manifest's pointer remains
    assert not obj.users_collection
    assert obj in _claims()


def test_a_deleted_datablock_leaves_an_entry_that_claims_nothing(sync: Synchronization, tmp_path: Path) -> None:
    # Removing it from bpy.data clears every pointer to it.
    _managed(sync, tmp_path)
    bpy.data.objects.remove(bpy.data.objects["Shot0"])
    manifest = ownership.read_manifest(bpy.data.collections["Shot"])
    assert isinstance(manifest, Loaded)
    assert manifest.record.entries["a"].datablock is None
    assert len(_claims()) == 2


def test_a_bindings_own_manifest(sync: Synchronization, tmp_path: Path) -> None:
    first, manifest = _managed(sync, tmp_path, "First")
    second, _ = _managed(sync, tmp_path, "Second")
    assert ownership.binding_manifest(first.binding_id) == Loaded(manifest, 1)
    assert ownership.binding_manifest(second.binding_id) != ownership.binding_manifest(first.binding_id)
    without = sync.create_attached_binding(_scene(), "shot")
    assert ownership.binding_manifest(without.binding_id) is None  # nothing managed yet
    with pytest.raises(KeyError):
        ownership.binding_manifest("not-a-binding")


def test_a_bindings_manifest_through_a_configuration_it_cannot_read(sync: Synchronization, tmp_path: Path) -> None:
    handle, _ = _managed(sync, tmp_path)
    config = _scene()[NAMESPACE]["binding." + handle.binding_id]
    config[VERSION_KEY] = 2
    result = ownership.binding_manifest(handle.binding_id)
    assert isinstance(result, Refused)
    assert result.kind == "binding"


def test_a_removed_destination_has_no_manifest(sync: Synchronization, tmp_path: Path) -> None:
    handle, _ = _managed(sync, tmp_path)
    bpy.data.collections.remove(bpy.data.collections["Shot"])
    assert ownership.binding_manifest(handle.binding_id) is None


def test_dependents_invert_the_uses(sync: Synchronization, tmp_path: Path) -> None:
    _, manifest = _managed(sync, tmp_path)
    assert ownership.dependents(manifest) == {"mesh": {"a", "b"}, "a": set(), "b": set()}


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"role": ""}, "an entry has a representation role"),
        # Not a list at all: ID properties can't hold a list mixing strings and ints.
        ({"covers": "/World"}, "an entry covers a list of source-entity paths"),
        ({"uses": ["nowhere"]}, "entries use resources the manifest doesn't have"),
    ],
)
def test_an_invalid_manifest_is_refused(
    sync: Synchronization, tmp_path: Path, change: dict[str, object], problem: str
) -> None:
    _managed(sync, tmp_path)
    destination = bpy.data.collections["Shot"]
    stored = destination[NAMESPACE][ownership.MANIFEST_KEY].to_dict()
    stored["entries"]["a"] |= change
    destination[NAMESPACE][ownership.MANIFEST_KEY] = stored
    result = ownership.read_manifest(destination)
    assert isinstance(result, Refused)
    assert result.refusal is Refusal.INVALID
    assert problem in result.message
    found, unreadable = ownership.claims()
    assert found == {}
    assert unreadable == [result]


def test_a_newer_manifest_is_refused_and_kept(sync: Synchronization, tmp_path: Path) -> None:
    # It claims nothing and is reported, and writing doesn't replace it.
    _, manifest = _managed(sync, tmp_path)
    destination = bpy.data.collections["Shot"]
    destination[NAMESPACE][ownership.MANIFEST_KEY][VERSION_KEY] = 2
    stored = destination[NAMESPACE][ownership.MANIFEST_KEY].to_dict()
    result = ownership.read_manifest(destination)
    assert isinstance(result, Refused)
    assert result.refusal is Refusal.NEWER
    assert ownership.claims() == ({}, [result])
    with pytest.raises(RecordRefused):
        ownership.write_manifest(destination, manifest)
    assert destination[NAMESPACE][ownership.MANIFEST_KEY].to_dict() == stored
