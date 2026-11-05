"""Ownership metadata: the manifest, and what it makes managed (lifecycle.md#ownership-and-lifecycle; OWN-01, OWN-16).

Bindings come from the synchronization API on a fresh process state per test; their managed
content is made here, as M5's application layer will make it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest

from fixtures import source_access
from proscenium.binding import persistence, runtime
from proscenium.binding.persistence import Manifest, ManifestEntry, RepresentationRole, manifests, records
from proscenium.binding.persistence.records import (
    NAMESPACE,
    VERSION_KEY,
    Loaded,
    RefusalReason,
    RefusedRecord,
    RefusedRecordError,
)
from proscenium.binding.runtime import ownership_index
from proscenium.binding.runtime.ownership_index import Claim
from proscenium.binding.source_access.binding_ids import BindingId
from support import ownership as oracle
from support.blend import save_and_reopen
from support.manifests import key, object_entry
from support.usd import binding_on_file

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from proscenium.api.bindings import BindingHandle, Bindings


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _managed(bindings: Bindings, tmp_path: Path, name: str = "Shot") -> tuple[BindingHandle, Manifest]:
    """A binding whose destination holds two managed objects sharing a managed mesh, and its manifest."""
    with source_access.binding_state(tmp_path / name) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root, name=name)
    destination = bpy.data.collections[name]
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    objects = [bpy.data.objects.new(f"{name}{i}", mesh) for i in range(2)]
    for obj in objects:
        destination.objects.link(obj)
    manifest = _manifest(mesh, *objects)
    ownership_index.set_manifest(handle.binding_id, manifest)  # the writer path: memory, then the record
    return handle, manifest


def _manifest(mesh: bpy.types.Mesh, a: bpy.types.Object, b: bpy.types.Object) -> Manifest:
    return Manifest(
        {
            key("mesh"): ManifestEntry(mesh, ["/World/Ref", "/World/Pay"], RepresentationRole.MESH, []),
            key("a"): object_entry(a, "/World/Ref", ("mesh",)),
            key("b"): object_entry(b, "/World/Pay", ("mesh",)),
        }
    )


def _claims() -> dict[bpy.types.ID, tuple[Claim, ...]]:
    """Every claimed datablock's claims, through the ownership index.

    The oracle, reading the records now, must agree.
    """
    oracle.assert_agrees()
    return {id_: claims for id_ in bpy.data.user_map() if (claims := ownership_index.ownership(id_).claims)}


def test_a_manifest_survives_save_and_reopen(bindings: Bindings, tmp_path: Path) -> None:
    # OWN-01: the entry key, datablock, coverage, role, place, and uses, each its own field.
    _managed(bindings, tmp_path)
    save_and_reopen(tmp_path / "manifest.blend")
    expected = _manifest(bpy.data.meshes["ShotMesh"], bpy.data.objects["Shot0"], bpy.data.objects["Shot1"])
    read = manifests.read_manifest(bpy.data.collections["Shot"])
    assert read == Loaded(expected, 1)
    assert all(type(e.role) is RepresentationRole for e in read.record.entries.values())


def test_nothing_is_stored_on_the_managed_datablocks(bindings: Bindings, tmp_path: Path) -> None:
    _managed(bindings, tmp_path)
    for datablock in (bpy.data.meshes["ShotMesh"], bpy.data.objects["Shot0"]):
        assert NAMESPACE not in datablock


def test_the_manifest_names_what_is_managed(bindings: Bindings, tmp_path: Path) -> None:
    # OWN-16: one claim each, from the binding whose manifest names it.
    handle, _ = _managed(bindings, tmp_path)
    shot = bpy.data.collections["Shot"]
    assert _claims() == {
        bpy.data.meshes["ShotMesh"]: (Claim(handle.binding_id, shot, key("mesh")),),
        bpy.data.objects["Shot0"]: (Claim(handle.binding_id, shot, key("a")),),
        bpy.data.objects["Shot1"]: (Claim(handle.binding_id, shot, key("b")),),
    }


def test_content_two_manifests_name_is_ambiguous(bindings: Bindings, tmp_path: Path) -> None:
    first, _ = _managed(bindings, tmp_path, "First")
    second, _ = _managed(bindings, tmp_path, "Second")
    shared = bpy.data.objects["First0"]
    manifest = manifests.read_manifest(bpy.data.collections["Second"])
    assert isinstance(manifest, Loaded)
    entries = {**manifest.record.entries, key("stolen"): object_entry(shared, "/World/Ref")}
    ownership_index.set_manifest(second.binding_id, Manifest(entries))
    first_claim = Claim(first.binding_id, bpy.data.collections["First"], key("a"))
    stolen = Claim(second.binding_id, bpy.data.collections["Second"], key("stolen"))
    assert _claims()[shared] == (first_claim, stolen)
    assert ownership_index.ownership(shared).status is ownership_index.OwnershipStatus.AMBIGUOUS


def test_a_manifest_names_a_datablock_once(bindings: Bindings, tmp_path: Path) -> None:
    # So two claims on a datablock always come from two manifests.
    _, manifest = _managed(bindings, tmp_path)
    twice = manifest.entries[key("a")]
    with pytest.raises(ValueError, match="two entries name one datablock"):
        Manifest({**manifest.entries, key("again"): twice})


def test_a_linked_copy_scene_shares_one_manifest(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Both scenes' configurations point at the one destination, which is read once: one claim each.
    handle, _ = _managed(bindings, tmp_path)
    window = bpy.context.window
    assert window is not None
    window.scene = _scene()
    bpy.ops.scene.new(type="LINK_COPY")
    assert len(bpy.data.scenes) == 2
    shot = bpy.data.collections["Shot"]
    read: list[bpy.types.Collection] = []
    read_manifest = persistence.read_manifest

    def counted(destination: bpy.types.Collection) -> object:
        read.append(destination)
        return read_manifest(destination)

    monkeypatch.setattr(persistence, "read_manifest", counted)
    runtime.invalidate()  # so the index is rebuilt from the records, reading what it reads
    found = {obj: claims for obj in bpy.data.objects if (claims := ownership_index.ownership(obj).claims)}
    assert read == [shot]
    assert {obj: claims for obj, claims in found.items() if obj in set(shot.objects)} == {
        bpy.data.objects["Shot0"]: (Claim(handle.binding_id, shot, key("a")),),
        bpy.data.objects["Shot1"]: (Claim(handle.binding_id, shot, key("b")),),
    }


def test_deleting_in_the_interface_keeps_the_content_claimed(bindings: Bindings, tmp_path: Path) -> None:
    # The manifest's pointer is a user, so Object > Delete unlinks the object but leaves it in the file,
    # still named, until a refresh or cleanup finds it linked nowhere.
    _managed(bindings, tmp_path)
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


def test_a_deleted_datablock_leaves_an_entry_that_claims_nothing(bindings: Bindings, tmp_path: Path) -> None:
    # Removing it from bpy.data clears every pointer to it.
    _managed(bindings, tmp_path)
    bpy.data.objects.remove(bpy.data.objects["Shot0"])
    manifest = manifests.read_manifest(bpy.data.collections["Shot"])
    assert isinstance(manifest, Loaded)
    assert manifest.record.entries[key("a")].datablock is None
    assert len(_claims()) == 2


def test_a_bindings_own_manifest(bindings: Bindings, tmp_path: Path) -> None:
    first, manifest = _managed(bindings, tmp_path, "First")
    second, _ = _managed(bindings, tmp_path, "Second")
    assert ownership_index.manifest(first.binding_id) == Loaded(manifest, 1)
    assert ownership_index.manifest(second.binding_id) != ownership_index.manifest(first.binding_id)
    without = bindings.create_binding(_scene())
    assert ownership_index.manifest(without.binding_id) is None  # nothing managed yet
    with pytest.raises(KeyError):
        ownership_index.manifest(BindingId("not-a-binding"))


def test_a_bindings_manifest_through_a_configuration_it_cannot_read(bindings: Bindings, tmp_path: Path) -> None:
    handle, _ = _managed(bindings, tmp_path)
    config = _scene()[NAMESPACE]["binding." + handle.binding_id]
    config[VERSION_KEY] = 2
    save_and_reopen(tmp_path / "edited.blend")  # the state sees a record edited behind it once it's reloaded
    result = ownership_index.manifest(handle.binding_id)
    assert isinstance(result, RefusedRecord)
    assert result.kind == "binding"


def test_a_removed_destination_has_no_manifest(bindings: Bindings, tmp_path: Path) -> None:
    handle, _ = _managed(bindings, tmp_path)
    bpy.data.collections.remove(bpy.data.collections["Shot"])
    assert ownership_index.manifest(handle.binding_id) is None  # the configuration's pointer was cleared


def test_dependents_invert_the_uses(bindings: Bindings, tmp_path: Path) -> None:
    _, manifest = _managed(bindings, tmp_path)
    assert manifests.dependents(manifest) == {key("mesh"): {key("a"), key("b")}, key("a"): set(), key("b"): set()}


def test_a_prepared_resource_takes_the_key_of_the_entry_with_its_identity(bindings: Bindings, tmp_path: Path) -> None:
    # ROLE-05: matched by role, source entity, and place; a new identity gets a new key. A content-keyed entry has none.
    _, manifest = _managed(bindings, tmp_path)
    object_at = manifests.CopyResourceIdentity(RepresentationRole.OBJECT, "/World/Pay", 0)
    found, other_place, other_role = manifests.entry_keys(
        manifest,
        [object_at, object_at._replace(place=1), object_at._replace(role=RepresentationRole.BOUNDS_MESH)],
    )
    assert found == key("b")
    assert len({other_place, other_role, *manifest.entries}) == 5
    assert manifest.entries[key("mesh")].identity is None


def test_entry_keys_are_random_and_stored_as_keys() -> None:
    keys = {manifests.new_entry_key() for _ in range(100)}
    assert len(keys) == 100
    assert all(len(k) == 32 and int(k, 16) >= 0 for k in keys)


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"role": ""}, "is not a valid RepresentationRole"),
        ({"role": "hologram"}, "is not a valid RepresentationRole"),  # ROLE-01: outside the vocabulary
        ({"place": None}, "has a place among its copy's objects"),
        ({"place": -1}, "has a place among its copy's objects"),
        ({"covers": ["/World/Ref", "/World/Pay"]}, "covers one source entity"),
        # Not a list at all: ID properties can't hold a list mixing strings and ints.
        ({"covers": "/World"}, "an entry covers a list of source-entity paths"),
        ({"uses": ["nowhere"]}, "entries use resources the manifest doesn't have"),
    ],
)
def test_an_invalid_manifest_is_refused(
    bindings: Bindings, tmp_path: Path, change: dict[str, object], problem: str
) -> None:
    handle, _ = _managed(bindings, tmp_path)
    destination = bpy.data.collections["Shot"]
    stored = destination[NAMESPACE][manifests.MANIFEST_KEY].to_dict()
    stored["entries"][key("a")] |= change
    destination[NAMESPACE][manifests.MANIFEST_KEY] = stored
    result = manifests.read_manifest(destination)
    assert isinstance(result, RefusedRecord)
    assert result.refusal is RefusalReason.INVALID
    assert problem in result.message
    runtime.invalidate()  # the record changed behind the state, as a load or undo changes it
    assert _claims() == {}
    assert ownership_index.manifest(handle.binding_id) == result


def test_a_newer_manifest_is_refused_and_kept(bindings: Bindings, tmp_path: Path) -> None:
    # It claims nothing and is reported, and writing doesn't replace it.
    handle, manifest = _managed(bindings, tmp_path)
    destination = bpy.data.collections["Shot"]
    destination[NAMESPACE][manifests.MANIFEST_KEY][VERSION_KEY] = 2
    stored = destination[NAMESPACE][manifests.MANIFEST_KEY].to_dict()
    result = manifests.read_manifest(destination)
    assert isinstance(result, RefusedRecord)
    assert result.refusal is RefusalReason.NEWER
    runtime.invalidate()  # the record changed behind the state, as a load or undo changes it
    assert _claims() == {}
    assert ownership_index.manifest(handle.binding_id) == result
    with pytest.raises(RefusedRecordError):
        manifests.write_manifest(destination, manifest)
    assert destination[NAMESPACE][manifests.MANIFEST_KEY].to_dict() == stored


def _entry(datablock: bpy.types.ID, uses: tuple[str, ...] = ()) -> ManifestEntry:
    return object_entry(datablock, "/World/Ref", uses)


# Updates to the manifest on _managed's destination, given its objects and a new one: (changed, removed), and
# the error with its message.
type _Update = Callable[[list[bpy.types.Object], bpy.types.Object], tuple[dict[str, Any], list[str]]]
_UPDATES: dict[str, tuple[_Update, type[Exception], str]] = {
    "removes a used resource": (
        lambda _, new: ({}, [key("mesh")]),
        ValueError,
        "use resources the manifest doesn't have",
    ),
    "uses a missing resource": (
        lambda _, new: ({key("c"): _entry(new, ("nowhere",))}, []),
        ValueError,
        "use resources the manifest doesn't have",
    ),
    "names a named datablock": (
        lambda objects, _: ({key("c"): _entry(objects[0])}, []),
        ValueError,
        "name one datablock",
    ),
    "names a datablock twice": (
        lambda _, new: ({key("c"): _entry(new), key("d"): _entry(new)}, []),
        ValueError,
        "name one datablock",
    ),
    "changes and removes one": (
        lambda _, new: ({key("a"): _entry(new)}, [key("a")]),
        ValueError,
        "both changes and removes",
    ),
    "removes a missing resource": (lambda _, new: ({}, [key("nowhere")]), ValueError, "removes resources"),
    "is not an entry": (
        lambda _, new: (
            {key("c"): {"datablock": new, "covers": ["/World"], "role": "object", "uses": [], "place": 0}},
            [],
        ),
        TypeError,
        "not a ManifestEntry",
    ),
    "covers a non-path": (
        lambda _, new: ({key("c"): ManifestEntry(new, [1], RepresentationRole.OBJECT, [], 0)}, []),  # ty: ignore[invalid-argument-type]
        TypeError,
        "all strings",
    ),
    "has a key that isn't an entry key": (lambda _, new: ({"c": _entry(new)}, []), ValueError, "32 hex digits"),
}


@pytest.mark.parametrize("update", _UPDATES)
def test_an_update_that_makes_no_manifest_changes_nothing(bindings: Bindings, tmp_path: Path, update: str) -> None:
    # Checked as a whole manifest is, before anything is written.
    handle, manifest = _managed(bindings, tmp_path)
    destination = bpy.data.collections["Shot"]
    objects = [bpy.data.objects["Shot0"], bpy.data.objects["Shot1"]]
    new = bpy.data.objects.new("New", None)
    stored = records.stored(destination, manifests.MANIFEST_KEY)
    claims = {obj: ownership_index.ownership(obj).claims for obj in [*objects, new]}
    make, error, message = _UPDATES[update]
    changed, removed = make(objects, new)
    with pytest.raises(error, match=message):
        ownership_index.set_manifest_entries(handle.binding_id, changed, removed)
    assert records.stored(destination, manifests.MANIFEST_KEY) == stored
    assert ownership_index.manifest(handle.binding_id) == Loaded(manifest, 1)
    assert {obj: ownership_index.ownership(obj).claims for obj in [*objects, new]} == claims
