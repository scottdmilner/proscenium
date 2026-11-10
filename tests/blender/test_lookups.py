"""Lookups on the bindings' records return current datablocks or nothing, never a removed one (UNDO-07).

lifecycle.md#undo-and-runtime-state. On F-BINDING-STATE. Every lookup reads the records when it's called, so
file loads, undo, redo, and removals no handler announces need nothing done (DECISIONS.md "Binding records read
when called").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import source_access
from proscenium.binding import persistence, runtime
from proscenium.binding.persistence import configs, manifests, records
from proscenium.binding.persistence.manifests import Manifest, ManifestEntry, RepresentationRole
from proscenium.binding.persistence.records import LoadedRecord, RefusedRecord, RefusedRecordError
from proscenium.binding.runtime import ownership
from proscenium.binding.runtime.ownership import Claim
from proscenium.binding.source_access.stages import PayloadPolicy
from support import ownership as oracle
from support import undo
from support.blend import save_and_reopen
from support.manifests import key, object_change, object_entry
from support.usd import binding_on_file

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.api.bindings import BindingHandle, Bindings
    from proscenium.binding.persistence.configs import BindingConfig
    from proscenium.binding.persistence.manifests import ManifestEntryChange
    from proscenium.binding.source_access.identifiers import BindingId


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _managed(bindings: Bindings, tmp_path: Path) -> BindingHandle:
    """A binding on F-BINDING-STATE whose destination holds one managed object, entry "a"."""
    with source_access.binding_state(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root, name="Shot")
    obj = bpy.data.objects.new("Managed", None)
    bpy.data.collections["Shot"].objects.link(obj)
    ownership.set_manifest(handle.binding_id, Manifest({key("a"): object_entry(obj, "/World")}))
    return handle


def _config(handle: BindingHandle) -> BindingConfig:
    found = runtime.binding_configs.find_binding(handle.binding_id)
    assert found is not None and found.config is not None
    return found.config


def _scene_of(binding_id: BindingId) -> bpy.types.Scene | None:
    """The scene holding the binding's canonical record, or None if there's no such binding."""
    found = runtime.binding_configs.find_binding(binding_id)
    return None if found is None else found.scene


def _binding_ids(scene: bpy.types.Scene | None = None) -> list[BindingId]:
    return [found.binding_id for found in runtime.binding_configs.find_bindings(scene)]


def _resource(binding_id: BindingId, name: str) -> bpy.types.ID | None:
    """The datablock of the binding's manifest entry called name, or None if there's no such binding or entry."""
    if runtime.binding_configs.find_binding(binding_id) is None:
        return None
    manifest = ownership.manifest(binding_id)
    entry = manifest.record.entries.get(key(name)) if isinstance(manifest, LoadedRecord) else None
    return None if entry is None else entry.datablock


def test_undo_and_redo_of_creation(bindings: Bindings, tmp_path: Path) -> None:
    # UNDO-07: after undo the binding isn't found; after redo, its scene is the current one.
    undo.require_global_undo()
    undo.push("base")
    handle = _managed(bindings, tmp_path)
    assert _scene_of(handle.binding_id) == _scene()
    undo.push("create")
    undo.undo()
    assert _scene_of(handle.binding_id) is None
    undo.redo()
    assert _scene_of(handle.binding_id) == _scene()
    assert _resource(handle.binding_id, "a") == bpy.data.objects["Managed"]


def test_undo_of_a_change_to_managed_content(bindings: Bindings, tmp_path: Path) -> None:
    # Undo leaves no stale lookup of what the step changed, as a synchronization changes managed content.
    undo.require_global_undo()
    handle = _managed(bindings, tmp_path)
    assert _resource(handle.binding_id, "a") == bpy.data.objects["Managed"]
    undo.push("base")
    bpy.data.objects["Managed"].location.x = 5.0
    undo.push("sync")
    undo.undo()
    current = bpy.data.objects["Managed"]
    assert _resource(handle.binding_id, "a") == current
    assert ownership.of(current).claims == (Claim(handle.binding_id, bpy.data.collections["Shot"], key("a")),)


def test_undo_reverts_a_configuration(bindings: Bindings, tmp_path: Path) -> None:
    # Undo restores the record, and the next lookup reads it.
    undo.require_global_undo()
    handle = _managed(bindings, tmp_path)
    undo.push("base")
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert _config(handle).settings.payload_policy is PayloadPolicy.LOAD_NONE
    undo.push("settings")
    undo.undo()
    assert _config(handle).settings.payload_policy is PayloadPolicy.LOAD_ALL


def _two_managed(bindings: Bindings, tmp_path: Path) -> tuple[list[BindingId], list[str]]:
    """_managed's binding, and Other managing two objects, A and B, with the index built.

    Returns their identifiers, and the names of the entries to look up.
    """
    handle = _managed(bindings, tmp_path)
    with source_access.binding_state(tmp_path) as scene:
        other = binding_on_file(bindings, _scene(), scene.root, name="Other")
    ownership.set_manifest(other.binding_id, _entries(*(bpy.data.objects.new(name, None) for name in ("A", "B"))))
    ids, names = [handle.binding_id, other.binding_id], ["managed", "a", "b"]
    assert _ownership_view(ids, names)
    return ids, names


def _counted_reads(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Every record read from here on, as (ID name, key)."""
    reads: list[tuple[str, str]] = []
    read = records.read

    def counted_read(id_: bpy.types.ID, key: str, schema: object) -> object:
        reads.append((id_.name, key))
        return read(id_, key, schema)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr(records, "read", counted_read)
    return reads


@pytest.mark.parametrize("lookup", ["resource", "manifest"])
def test_a_removed_datablock_is_gone_from_its_manifest(bindings: Bindings, tmp_path: Path, lookup: str) -> None:
    # UNDO-07: Blender clears a removed datablock's pointer in the records, so a lookup finds nothing there, and the
    # other entries and bindings are as they were.
    ids, names = _two_managed(bindings, tmp_path)
    other = ids[1]
    bpy.data.objects.remove(bpy.data.objects["A"])
    if lookup == "resource":
        assert _resource(other, "a") is None
    else:
        found = ownership.manifest(other)
        assert isinstance(found, LoadedRecord)
        assert found.record.entries[key("a")].datablock is None
    assert _resource(other, "b") == bpy.data.objects["B"]
    assert _resource(ids[0], "a") == bpy.data.objects["Managed"]  # Shot's entry "a"
    oracle.assert_agrees()


def _entry(datablock: bpy.types.ID, uses: tuple[str, ...] = ()) -> ManifestEntry:
    return object_entry(datablock, "/World", uses)


def _change(uses: tuple[str, ...] = ()) -> ManifestEntryChange:
    return object_change("/World", uses)


def test_an_update_writes_and_indexes_only_what_changes(bindings: Bindings, tmp_path: Path) -> None:
    # An incremental refresh changes some resources; an update writes only those, and the records then answer for it.
    ids, _ = _two_managed(bindings, tmp_path)
    other, destination = ids[1], bpy.data.collections["Other"]
    a, b = bpy.data.objects["A"], bpy.data.objects["B"]
    c, d = bpy.data.objects.new("C", None), bpy.data.objects.new("D", None)
    # An entry stored by hand: the update reads it, and keeps it, so a whole write would show as its loss.
    destination[records.NAMESPACE][manifests.MANIFEST_KEY]["entries"][key("marker")] = {
        "datablock": None,
        "covers": ["/World/Marker"],
        "role": "object",
        "uses": [],
        "place": 0,
    }
    # b keeps its datablock and covers another path; c and d are new, and d uses c.
    ownership.set_manifest_entries(
        other,
        {key("b"): object_change("/World/Kept"), key("c"): _change(), key("d"): _change(("c",))},
        [key("a")],
        {key("c"): c, key("d"): d},
    )
    assert [_resource(other, r) for r in ("a", "b", "c", "d")] == [None, b, c, d]
    found = ownership.manifest(other)
    assert isinstance(found, LoadedRecord)
    assert found.record.entries[key("b")] == object_entry(b, "/World/Kept")
    assert ownership.of(a).claims == ()
    assert ownership.of(c).claims == (Claim(other, destination, key("c")),)
    entries = destination[records.NAMESPACE][manifests.MANIFEST_KEY]["entries"]
    assert key("marker") in entries
    oracle.assert_agrees()


@pytest.mark.parametrize("first_removed", ["Other", "Shot"])
def test_a_datablock_claimed_twice_and_once_again(bindings: Bindings, tmp_path: Path, first_removed: str) -> None:
    # Removing either claim of an ambiguous datablock leaves it managed by the other.
    ids, names = _two_managed(bindings, tmp_path)
    handle, other = ids
    a = bpy.data.objects["A"]
    by_name = {
        "Other": Claim(other, bpy.data.collections["Other"], key("a")),
        "Shot": Claim(handle, bpy.data.collections["Shot"], key("x")),
    }
    stored = ownership.manifest(handle)
    assert isinstance(stored, LoadedRecord)
    ownership.set_manifest(handle, Manifest({**stored.record.entries, key("x"): _entry(a)}))
    assert ownership.of(a).status is ownership.OwnershipStatus.AMBIGUOUS
    assert set(ownership.of(a).claims) == set(by_name.values())
    in_place = _ownership_view(ids, [*names, "x"])
    assert in_place == _ownership_view(ids, [*names, "x"])
    if first_removed == "Other":
        ownership.set_manifest_entries(other, {}, [key("a")])
    else:
        ownership.set_manifest_entries(handle, {}, [key("x")])
    [kept] = [claim for name, claim in by_name.items() if name != first_removed]
    assert ownership.of(a) == ownership.Ownership((kept,))
    assert ownership.of(a).status is ownership.OwnershipStatus.MANAGED
    in_place = _ownership_view(ids, [*names, "x"])
    assert in_place == _ownership_view(ids, [*names, "x"])


def test_an_empty_update_writes_nothing(bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A no-op refresh performs no Blender writes (incremental.md#affected-content).
    handle = _managed(bindings, tmp_path)

    def no_writes(*_args: object) -> None:
        raise AssertionError("a record was written")

    monkeypatch.setattr(records, "write", no_writes)
    monkeypatch.setattr(records, "write_items", no_writes)
    ownership.set_manifest_entries(handle.binding_id, {}, [])


def test_an_update_to_a_binding_without_a_manifest(bindings: Bindings, tmp_path: Path) -> None:
    with source_access.binding_state(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root, name="Shot")
    assert ownership.manifest(handle.binding_id) is None
    obj = bpy.data.objects.new("Managed", None)
    ownership.set_manifest_entries(handle.binding_id, {key("a"): _change()}, created={key("a"): obj})
    expected = LoadedRecord(Manifest({key("a"): _entry(obj)}), manifests.MANIFEST.version)
    assert ownership.manifest(handle.binding_id) == expected
    assert ownership.manifest(handle.binding_id) == manifests.read_manifest(bpy.data.collections["Shot"])
    assert _resource(handle.binding_id, "a") == obj


def test_an_update_from_the_manifest_its_caller_read(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given the manifest as read, the update doesn't read it again, and writes what reading it would have.
    ids, _names = _two_managed(bindings, tmp_path)
    other = ids[1]
    stored = ownership.manifest(other)
    assert isinstance(stored, LoadedRecord)
    replacement = bpy.data.objects.new("Replacement", None)

    def no_reads(*_args: object) -> None:
        raise AssertionError("the manifest was read")

    with monkeypatch.context() as patch:
        patch.setattr(manifests, "read_manifest", no_reads)
        ownership.set_manifest_entries(
            other, {key("b"): _change()}, [key("a")], {key("b"): replacement}, published=stored.record
        )
    expected = stored.record.updated({key("b"): _change()}, [key("a")], {key("b"): replacement})
    assert ownership.manifest(other) == LoadedRecord(expected, manifests.MANIFEST.version)


@pytest.mark.parametrize("removed", [["a"], ["a", "a"], []])
def test_an_update_after_a_removal(bindings: Bindings, tmp_path: Path, removed: list[str]) -> None:
    # The removed datablock's entry, which Blender cleared, is removed by the update, once even if named twice,
    # or carried into its result.
    ids, names = _two_managed(bindings, tmp_path)
    other = ids[1]
    bpy.data.objects.remove(bpy.data.objects["A"])
    replacement = bpy.data.objects.new("Replacement", None)
    changed, made = {key("b"): _change()}, {key("b"): replacement}
    ownership.set_manifest_entries(other, changed, [key(name) for name in removed], made)
    assert ownership.manifest(other) == manifests.read_manifest(bpy.data.collections["Other"])
    in_place = _ownership_view(ids, names)
    assert _resource(other, "b") == replacement
    assert in_place == _ownership_view(ids, names)


def test_a_new_datablock_at_a_removed_ones_address_is_unmanaged(bindings: Bindings, tmp_path: Path) -> None:
    handle = _managed(bindings, tmp_path)
    removed = bpy.data.objects["Managed"]
    assert ownership.of(removed).claims == (Claim(handle.binding_id, bpy.data.collections["Shot"], key("a")),)
    address = removed.as_pointer()
    bpy.data.objects.remove(removed)
    # The case under test is a new object in the freed memory; the allocator may hand it out a few allocations later.
    new = next((o for o in (bpy.data.objects.new("New", None) for _ in range(100)) if o.as_pointer() == address), None)
    assert new is not None, "no new object took the removed one's address"
    assert ownership.of(new).claims == ()


def test_a_removed_destination(bindings: Bindings, tmp_path: Path) -> None:
    handle = _managed(bindings, tmp_path)
    obj = bpy.data.objects["Managed"]
    assert ownership.of(obj).claims
    bpy.data.collections.remove(bpy.data.collections["Shot"])
    # DEST-05, DEST-07: the binding went with its records, and its manifest with them, though the object remains.
    assert runtime.binding_configs.find_binding(handle.binding_id) is None
    assert _resource(handle.binding_id, "a") is None
    with pytest.raises(KeyError):
        ownership.manifest(handle.binding_id)
    assert ownership.of(obj).claims == ()


@pytest.mark.parametrize("asked", ["claims", "update"])
def test_a_destination_removed_after_a_lookup(bindings: Bindings, tmp_path: Path, asked: str) -> None:
    # The next lookup reads the records without the removed destination; the other binding is as it was.
    ids, _ = _two_managed(bindings, tmp_path)
    assert sorted(_binding_ids()) == sorted(ids)
    bpy.data.collections.remove(bpy.data.collections["Shot"])
    if asked == "claims":
        assert ownership.of(bpy.data.objects["Managed"]).claims == ()
    else:
        ownership.set_manifest_entries(
            ids[1], {key("c"): _change()}, created={key("c"): bpy.data.objects.new("C", None)}
        )
        assert _resource(ids[1], "c") == bpy.data.objects["C"]
    assert [c.binding_id for c in ownership.of(bpy.data.objects["A"]).claims] == [ids[1]]


def test_a_resource_is_read_through_its_bindings_manifest_alone(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A binding's manifest() reads that binding's manifest alone, and ownership of a datablock only the manifests
    # among its users.
    ids, _ = _two_managed(bindings, tmp_path)
    reads = _counted_reads(monkeypatch)
    assert _resource(ids[1], "a") == bpy.data.objects["A"]
    assert [read for read in reads if read[1] == manifests.MANIFEST_KEY] == [("Other", manifests.MANIFEST_KEY)]
    reads.clear()
    assert [c.binding_id for c in ownership.of(bpy.data.objects["A"]).claims] == [ids[1]]
    assert [read for read in reads if read[1] == manifests.MANIFEST_KEY] == [("Other", manifests.MANIFEST_KEY)]


def _copy_scene(kind: str) -> bpy.types.Scene:
    assert bpy.context.scene == _scene()  # the scene the operator copies
    bpy.ops.scene.new(type=kind)  # ty: ignore[invalid-argument-type] - stubs type the enum as a literal union
    (copy,) = (scene for scene in bpy.data.scenes if scene != _scene())
    return copy


@pytest.mark.parametrize("kind", ["FULL_COPY", "LINK_COPY"])
def test_a_scene_copy_made_after_a_lookup(bindings: Bindings, tmp_path: Path, kind: str) -> None:
    # No handler announces a new scene. A full copy's destination is a candidate of the binding's identity, which
    # the index names the original's, so the original stays canonical and the copy is reported, not listed on its
    # scene (source-access.md#copied-bindings); a linked copy shares the destination, so it adds no candidate. The
    # manifests count as the oracle counts them.
    handle = _managed(bindings, tmp_path)
    assert ownership.of(bpy.data.objects["Managed"]).claims
    copy = _copy_scene(kind)
    assert bindings.in_scene(copy) == []
    assert bindings.in_scene(_scene()) == [handle]
    assert _scene_of(handle.binding_id) == _scene()  # lookups use the canonical candidate
    oracle.assert_agrees()
    if kind == "FULL_COPY":
        [copied] = bindings.copied()
        assert [(c.scene, c.canonical) for c in copied.candidates] == [("Scene", True), (copy.name, False)]
        (copied_object,) = (obj for obj in bpy.data.objects if obj.name != "Managed")
        destination = copy.collection.children[0]
        assert [c.destination for c in ownership.of(copied_object).claims] == [destination]
    else:  # the copy shares the destination, whose manifest counts once
        assert bindings.copied() == []
        assert len(ownership.of(bpy.data.objects["Managed"]).claims) == 1


def _ownership_view(binding_ids: list[BindingId], names: list[str]) -> object:
    """What lookups answer, by name: every object's claims, and the entries called names."""
    claims = {
        obj.name: {(c.binding_id, c.destination.name, c.entry_key) for c in ownership.of(obj).claims}
        for obj in bpy.data.objects
    }
    resources = {(b, r): getattr(_resource(b, r), "name", None) for b in binding_ids for r in names}
    return claims, resources


def _entries(*objects: bpy.types.Object) -> Manifest:
    return Manifest({key(obj.name.lower()): object_entry(obj, "/World") for obj in objects})


def test_a_publication_keeps_its_destinations_claimant(bindings: Bindings, tmp_path: Path) -> None:
    # Two identities' records on one destination, as damage leaves them: a publication through the second keeps the
    # claimant, the first record the destination holds. The second's own destination is removed, so it has no copy
    # and stays unique.
    handle = _managed(bindings, tmp_path)
    with source_access.binding_state(tmp_path) as scene:
        other = binding_on_file(bindings, _scene(), scene.root, name="Other")
    key_of_other = configs.config_key(other.binding_id)
    shot = bpy.data.collections["Shot"]
    shot[records.NAMESPACE][key_of_other] = bpy.data.collections["Other"][records.NAMESPACE][key_of_other]
    bpy.data.collections.remove(bpy.data.collections["Other"])
    ids, names = [handle.binding_id, other.binding_id], ["managed", "a"]
    ownership.set_manifest(other.binding_id, _entries(bpy.data.objects.new("A", None)))
    # One destination, one record.
    assert ownership.manifest(handle.binding_id) == ownership.manifest(other.binding_id)
    # Each identity's resources are what its manifest names, though the claims name the first.
    assert _resource(handle.binding_id, "a") == _resource(other.binding_id, "a") == bpy.data.objects["A"]
    assert [c.binding_id for c in ownership.of(bpy.data.objects["A"]).claims] == [handle.binding_id]
    in_place = _ownership_view(ids, names)
    assert in_place == _ownership_view(ids, names)


def test_a_removed_scene(bindings: Bindings, tmp_path: Path) -> None:
    other = bpy.data.scenes.new("Other")
    with source_access.binding_state(tmp_path) as scene:
        handle = binding_on_file(bindings, other, scene.root)
    assert _binding_ids() == [handle.binding_id]
    address = other.as_pointer()
    bpy.data.scenes.remove(other)
    assert _binding_ids() == []
    # A new scene in the freed memory doesn't pick up the removed one's bindings.
    new = next((s for s in (bpy.data.scenes.new("New") for _ in range(100)) if s.as_pointer() == address), None)
    assert new is not None, "no new scene took the removed one's address"
    assert bindings.in_scene(new) == []


def test_listing_a_scene_checks_only_its_bindings(bindings: Bindings, tmp_path: Path) -> None:
    # A binding on another scene isn't listed on this one; removing its destination removes it (DEST-05).
    other_scene = bpy.data.scenes.new("Other")
    with source_access.binding_state(tmp_path) as scene:
        elsewhere = binding_on_file(bindings, other_scene, scene.root, name="Elsewhere")
        here = binding_on_file(bindings, _scene(), scene.root, name="Here")
    assert bindings.in_scene(_scene()) == [here]
    assert bindings.in_scene(other_scene) == [elsewhere]
    bpy.data.collections.remove(bpy.data.collections["Elsewhere"])
    assert bindings.in_scene(_scene()) == [here]
    assert bindings.in_scene(other_scene) == []
    assert _binding_ids() == [here.binding_id]
    bpy.data.collections.remove(bpy.data.collections["Here"])
    assert bindings.in_scene(_scene()) == []


def test_release_reads_no_records(bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with source_access.binding_state(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root)
    handle.synchronize(0)
    stages = bindings.stages.get(handle.binding_id)
    assert stages is not None

    def refused() -> object:
        raise AssertionError("release must not read binding records")

    monkeypatch.setattr(persistence.configs, "read_configs", refused)
    assert handle.release() is None
    assert (stages.live_stage, stages.evaluation_stage) == (None, None)


def test_every_binding(bindings: Bindings, tmp_path: Path) -> None:
    # As find_binding() finds each: usable with its configuration, or unreadable with why, checked.
    readable = bindings.create_binding(_scene(), name="A")
    unreadable = bindings.create_binding(_scene(), name="B")
    bpy.data.collections["B"][records.NAMESPACE][configs.config_key(unreadable.binding_id)][records.VERSION_KEY] = 2
    found = runtime.binding_configs.find_bindings()
    assert found == [
        runtime.binding_configs.find_binding(readable.binding_id),
        runtime.binding_configs.find_binding(unreadable.binding_id),
    ]
    assert [f.usable for f in found] == [True, False]
    assert isinstance(found[1].unreadable, RefusedRecord)
    assert found[1].config is None
    with pytest.raises(RefusedRecordError):
        found[1].usable_config()


def test_a_configuration_record_removed_by_hand(bindings: Bindings, tmp_path: Path) -> None:
    # As from the Custom Properties panel with Developer Extras on: no handler, and no scene added or removed.
    handle = _managed(bindings, tmp_path)
    assert _binding_ids(_scene()) == [handle.binding_id]
    del bpy.data.collections["Shot"][records.NAMESPACE][configs.config_key(handle.binding_id)]
    assert _binding_ids(_scene()) == []


def test_a_handler_ahead_of_the_extensions(bindings: Bindings, tmp_path: Path) -> None:
    # Another extension's redo_post handler, running before the extension's, reads the redone data.
    undo.require_global_undo()
    undo.push("base")
    handle = _managed(bindings, tmp_path)
    undo.push("create")
    undo.undo()
    assert _binding_ids() == []
    seen: list[list[BindingId]] = []

    def ahead(*_args: object) -> None:
        seen.append(_binding_ids())

    bpy.app.handlers.redo_post.insert(0, ahead)
    try:
        undo.redo()
    finally:
        bpy.app.handlers.redo_post.remove(ahead)
    assert seen == [[handle.binding_id]]


def test_after_save_and_reopen(bindings: Bindings, tmp_path: Path) -> None:
    handle = _managed(bindings, tmp_path)
    assert _scene_of(handle.binding_id) == _scene()
    save_and_reopen(tmp_path / "indexes.blend")
    assert _scene_of(handle.binding_id) == _scene()
    assert _resource(handle.binding_id, "a") == bpy.data.objects["Managed"]


def test_a_manifest_cant_be_changed_through_a_caller(bindings: Bindings, tmp_path: Path) -> None:
    # Neither the lists a publisher gave a manifest nor the manifest a lookup returns can change what's stored.
    handle = _managed(bindings, tmp_path)
    covers, uses = ["/World"], []
    entries = {key("a"): ManifestEntry(bpy.data.objects["Managed"], covers, RepresentationRole.OBJECT, uses, 0)}
    ownership.set_manifest(handle.binding_id, Manifest(entries))
    covers.append("/Elsewhere")
    uses.append(key("a"))
    entries[key("b")] = object_entry(bpy.data.objects.new("B", None), "/World/B")
    found = ownership.manifest(handle.binding_id)
    assert isinstance(found, LoadedRecord)
    assert found == manifests.read_manifest(bpy.data.collections["Shot"])
    with pytest.raises((TypeError, AttributeError)):
        found.record.entries[key("c")] = entries[key("b")]  # ty: ignore[invalid-assignment] - the point: it's read-only
    with pytest.raises((TypeError, AttributeError)):
        found.record.entries[key("a")].covers.append("/Elsewhere")  # ty: ignore[unresolved-attribute]
    with pytest.raises((TypeError, AttributeError)):
        found.record.entries[key("a")].uses.append(key("a"))  # ty: ignore[unresolved-attribute]
    assert ownership.manifest(handle.binding_id) == manifests.read_manifest(bpy.data.collections["Shot"])


def test_a_struct_inside_a_datablock_is_not_invalidated_by_undo() -> None:
    # Why runtime code holds no references to data inside a datablock. A modifier held across undo of a step that
    # changed its object isn't invalidated: it names freed memory, so it's compared by address here, never read.
    # If this fails, Blender has started invalidating such references, and the hazard has changed.
    undo.require_global_undo()
    obj = bpy.data.objects.new("M", bpy.data.meshes.new("m"))
    _scene().collection.objects.link(obj)
    modifier = obj.modifiers.new("S", "SUBSURF")
    assert isinstance(modifier, bpy.types.SubsurfModifier)
    undo.push("base")
    modifier.levels = 3
    undo.push("sync")
    undo.undo()
    fresh = bpy.data.objects["M"].modifiers["S"]
    assert modifier.as_pointer() != fresh.as_pointer()
