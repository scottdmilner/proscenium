"""The bindings' in-memory state returns current datablocks or nothing, never a removed one (UNDO-07).

lifecycle.md#undo-and-runtime-state. On F-BINDING-STATE, with the extension registered, whose
load, undo, and redo handlers drop the state; removals no handler announces are caught by the
checks on each hit.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import bpy
import pytest
from pxr import Usd

from fixtures import source_access
from proscenium import addon, bindings, indexes, ownership, records
from proscenium.core.source_access import PayloadPolicy
from proscenium.ownership import Claim, Manifest, ManifestEntry
from proscenium.records import Loaded, Refused
from proscenium.synchronization import Synchronization
from support import undo
from support.blend import save_and_reopen

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.bindings import BindingConfig
    from proscenium.synchronization import BindingHandle


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _managed(sync: Synchronization, tmp_path: Path) -> BindingHandle:
    """A binding on F-BINDING-STATE whose destination holds one managed object, resource "a"."""
    with source_access.binding_state(tmp_path) as scene:
        handle = sync.create_file_binding(_scene(), scene.root, name="Shot")
    obj = bpy.data.objects.new("Managed", None)
    bpy.data.collections["Shot"].objects.link(obj)
    indexes.set_manifest(handle.binding_id, Manifest({"a": ManifestEntry(obj, ["/World"], "prim", [])}))
    return handle


def _config(handle: BindingHandle) -> BindingConfig:
    config = indexes.config(handle.binding_id)
    assert config is not None and not isinstance(config, Refused)
    return config


def test_undo_and_redo_of_creation(sync: Synchronization, tmp_path: Path) -> None:
    # UNDO-07: after undo the binding isn't found; after redo, its scene is the current one.
    undo.require_global_undo()
    undo.push("base")
    handle = _managed(sync, tmp_path)
    assert indexes.binding_scene(handle.binding_id) == _scene()
    undo.push("create")
    undo.undo()
    assert indexes.binding_scene(handle.binding_id) is None
    assert indexes.resource(handle.binding_id, "a") is None
    undo.redo()
    assert indexes.binding_scene(handle.binding_id) == _scene()
    assert indexes.resource(handle.binding_id, "a") == bpy.data.objects["Managed"]


def test_undo_of_a_change_to_managed_content(sync: Synchronization, tmp_path: Path) -> None:
    # Undo re-reads what the step changed, as a synchronization changes managed content.
    undo.require_global_undo()
    handle = _managed(sync, tmp_path)
    assert indexes.resource(handle.binding_id, "a") == bpy.data.objects["Managed"]
    undo.push("base")
    bpy.data.objects["Managed"].location.x = 5.0
    undo.push("sync")
    undo.undo()
    current = bpy.data.objects["Managed"]
    assert indexes.resource(handle.binding_id, "a") == current
    assert indexes.claims_on(current) == [Claim(handle.binding_id, bpy.data.collections["Shot"], "a")]


def test_undo_reverts_a_cached_configuration(sync: Synchronization, tmp_path: Path) -> None:
    # The state caches the decoded configuration; undo restores the record, and the handler drops the cache.
    undo.require_global_undo()
    handle = _managed(sync, tmp_path)
    undo.push("base")
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert _config(handle).payload_policy is PayloadPolicy.LOAD_NONE
    undo.push("settings")
    undo.undo()
    assert _config(handle).payload_policy is PayloadPolicy.LOAD_ALL


def test_removed_managed_content(sync: Synchronization, tmp_path: Path) -> None:
    # No handler announces it: the check on the hit does.
    handle = _managed(sync, tmp_path)
    assert indexes.resource(handle.binding_id, "a") is not None
    bpy.data.objects.remove(bpy.data.objects["Managed"])
    assert indexes.resource(handle.binding_id, "a") is None


def test_a_removed_datablock_leaves_the_cached_manifest(sync: Synchronization, tmp_path: Path) -> None:
    # The manifest in memory names the datablock; after the removal it shows what the record does.
    handle = _managed(sync, tmp_path)
    assert indexes.manifest(handle.binding_id) is not None
    bpy.data.objects.remove(bpy.data.objects["Managed"])
    found = indexes.manifest(handle.binding_id)
    assert isinstance(found, Loaded)
    assert found.record.entries["a"].datablock is None  # Blender cleared the stored pointer
    assert found == ownership.read_manifest(bpy.data.collections["Shot"])


def _two_managed(sync: Synchronization, tmp_path: Path) -> tuple[list[str], list[str]]:
    """_managed's binding, and Other managing two objects, A and B; with the index built. Their identifiers,
    and the resource identities to look up."""
    handle = _managed(sync, tmp_path)
    with source_access.binding_state(tmp_path) as scene:
        other = sync.create_file_binding(_scene(), scene.root, name="Other")
    indexes.set_manifest(other.binding_id, _entries(*(bpy.data.objects.new(name, None) for name in ("A", "B"))))
    ids, names = [handle.binding_id, other.binding_id], ["managed", "a", "b"]
    assert _ownership_view(ids, names)
    return ids, names


def _counted_reads(monkeypatch: pytest.MonkeyPatch) -> tuple[list[tuple[str, str]], list[object]]:
    """Every record read from here on, as (ID name, key), and every share of the ownership index built."""
    reads: list[tuple[str, str]] = []
    shares: list[object] = []
    read, claims_from = records.read, ownership.claims_from

    def counted_read(id_: bpy.types.ID, key: str, schema: object) -> object:
        reads.append((id_.name, key))
        return read(id_, key, schema)  # ty: ignore[invalid-argument-type]

    def counted_share(manifests: list[object]) -> object:
        shares.append(manifests)
        return claims_from(manifests)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr(records, "read", counted_read)
    monkeypatch.setattr(ownership, "claims_from", counted_share)
    return reads, shares


@pytest.mark.parametrize("lookup", ["resource", "manifest"])
def test_a_removed_datablock_rereads_only_its_manifest(
    sync: Synchronization, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lookup: str
) -> None:
    # The cost of a removal doesn't grow with the rest of the file: the other binding's share and every
    # configuration stay, and the result is what a rebuild from the records gives.
    ids, names = _two_managed(sync, tmp_path)
    other = ids[1]
    rebuilds = indexes.rebuilds()
    reads, shares = _counted_reads(monkeypatch)
    bpy.data.objects.remove(bpy.data.objects["A"])
    if lookup == "resource":
        assert indexes.resource(other, "a") is None
    else:
        found = indexes.manifest(other)
        assert isinstance(found, Loaded)
        assert found.record.entries["a"].datablock is None
    assert reads == [("Other", ownership.MANIFEST_KEY)]
    assert indexes.rebuilds() == rebuilds
    assert indexes.resource(other, "b") == bpy.data.objects["B"]
    in_place = _ownership_view(ids, names)
    assert reads == [("Other", ownership.MANIFEST_KEY)]  # the share replaced holds no removed datablock
    assert len(shares) == 1  # Other's, replaced; the index isn't rebuilt
    indexes.invalidate()
    assert in_place == _ownership_view(ids, names)


def _entry(datablock: bpy.types.ID, uses: list[str] | None = None) -> ManifestEntry:
    return ManifestEntry(datablock, ["/World"], "prim", uses or [])


def test_an_update_writes_and_indexes_only_what_changes(
    sync: Synchronization, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Phase 2 refreshes change some resources; an update costs those, and its result is what a rebuild gives.
    ids, names = _two_managed(sync, tmp_path)
    other, destination = ids[1], bpy.data.collections["Other"]
    a, b = bpy.data.objects["A"], bpy.data.objects["B"]
    c, d = bpy.data.objects.new("C", None), bpy.data.objects.new("D", None)
    # An entry stored but not in the state: a whole write would drop it, so its staying shows none happened.
    destination[records.NAMESPACE][ownership.MANIFEST_KEY]["entries"]["marker"] = {
        "datablock": None,
        "covers": [],
        "role": "marker",
        "uses": [],
    }
    rebuilds = indexes.rebuilds()
    reads, shares = _counted_reads(monkeypatch)
    # b's datablock moves to c, and d uses c.
    indexes.update_manifest(other, {"b": _entry(c), "c": _entry(b), "d": _entry(d, ["c"])}, ["a"])
    names += ["c", "d"]
    in_place = _ownership_view(ids, names)
    assert (reads, shares, indexes.rebuilds()) == ([], [], rebuilds)  # nothing reread or rebuilt
    assert [indexes.resource(other, r) for r in ("a", "b", "c", "d")] == [None, c, b, d]
    assert indexes.claims_on(a) == []
    assert indexes.claims_on(b) == [Claim(other, destination, "c")]
    entries = destination[records.NAMESPACE][ownership.MANIFEST_KEY]["entries"]
    assert "marker" in entries
    del entries["marker"]
    assert indexes.manifest(other) == ownership.read_manifest(destination)
    indexes.invalidate()
    assert in_place == _ownership_view(ids, names)


def test_an_empty_update_writes_nothing(sync: Synchronization, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A no-op refresh performs no Blender writes (incremental.md#affected-content).
    handle = _managed(sync, tmp_path)

    def no_writes(*_args: object) -> None:
        raise AssertionError("a record was written")

    monkeypatch.setattr(records, "write", no_writes)
    monkeypatch.setattr(records, "write_items", no_writes)
    indexes.update_manifest(handle.binding_id, {}, [])


def test_an_update_to_a_binding_without_a_manifest(sync: Synchronization, tmp_path: Path) -> None:
    with source_access.binding_state(tmp_path) as scene:
        handle = sync.create_file_binding(_scene(), scene.root, name="Shot")
    assert indexes.manifest(handle.binding_id) is None
    obj = bpy.data.objects.new("Managed", None)
    indexes.update_manifest(handle.binding_id, {"a": _entry(obj)})
    assert indexes.manifest(handle.binding_id) == Loaded(Manifest({"a": _entry(obj)}), 1)
    assert indexes.manifest(handle.binding_id) == ownership.read_manifest(bpy.data.collections["Shot"])
    assert indexes.resource(handle.binding_id, "a") == obj


@pytest.mark.parametrize("removed", [["a"], []])
def test_an_update_after_a_removal(sync: Synchronization, tmp_path: Path, removed: list[str]) -> None:
    # The removed datablock's entry, which Blender cleared, is removed by the update or carried into its result.
    ids, names = _two_managed(sync, tmp_path)
    other = ids[1]
    bpy.data.objects.remove(bpy.data.objects["A"])
    replacement = bpy.data.objects.new("Replacement", None)
    indexes.update_manifest(other, {"b": _entry(replacement)}, removed)
    assert indexes.manifest(other) == ownership.read_manifest(bpy.data.collections["Other"])
    in_place = _ownership_view(ids, names)
    assert indexes.resource(other, "b") == replacement
    indexes.invalidate()
    assert in_place == _ownership_view(ids, names)


def test_a_new_datablock_at_a_removed_ones_address_is_unmanaged(sync: Synchronization, tmp_path: Path) -> None:
    handle = _managed(sync, tmp_path)
    removed = bpy.data.objects["Managed"]
    assert indexes.claims_on(removed) == [Claim(handle.binding_id, bpy.data.collections["Shot"], "a")]
    address = removed.as_pointer()
    bpy.data.objects.remove(removed)
    # The case under test is a new object in the freed memory; the allocator may hand it out a few allocations later.
    new = next((o for o in (bpy.data.objects.new("New", None) for _ in range(100)) if o.as_pointer() == address), None)
    assert new is not None, "no new object took the removed one's address"
    assert indexes.claims_on(new) == []


def test_a_removed_destination(sync: Synchronization, tmp_path: Path) -> None:
    handle = _managed(sync, tmp_path)
    obj = bpy.data.objects["Managed"]
    assert indexes.claims_on(obj)
    bpy.data.collections.remove(bpy.data.collections["Shot"])
    assert indexes.claims_on(obj) == []  # the manifest went with its collection
    assert _config(handle).destination is None  # Blender cleared the pointer, and the state was rebuilt


def _copy_scene(kind: str) -> bpy.types.Scene:
    assert bpy.context.scene == _scene()  # the scene the operator copies
    bpy.ops.scene.new(type=kind)  # ty: ignore[invalid-argument-type] - stubs type the enum as a literal union
    (copy,) = (scene for scene in bpy.data.scenes if scene != _scene())
    return copy


def _assert_ownership_agrees() -> None:
    # The state's claims are ownership.claims(), read from the records now, for every object.
    expected, _ = ownership.claims()
    for obj in bpy.data.objects:
        assert set(indexes.claims_on(obj)) == set(expected.get(obj, []))


@pytest.mark.parametrize("kind", ["FULL_COPY", "LINK_COPY"])
def test_a_scene_copy_made_after_the_state_was_built(sync: Synchronization, tmp_path: Path, kind: str) -> None:
    # No handler announces a new scene. The copy is a candidate of the binding's identity, its scene
    # lists it, and its manifest counts as ownership.claims counts it.
    handle = _managed(sync, tmp_path)
    assert indexes.claims_on(bpy.data.objects["Managed"])  # the state, ownership included, is built
    copy = _copy_scene(kind)
    assert sync.bindings(copy) == [handle]
    assert indexes.binding_scene(handle.binding_id) == _scene()  # lookups use the first candidate found
    _assert_ownership_agrees()
    if kind == "FULL_COPY":
        (copied,) = (obj for obj in bpy.data.objects if obj.name != "Managed")
        assert [c.destination for c in indexes.claims_on(copied)] == [copy.collection.children[0]]
    else:  # the copy shares the destination, whose manifest counts once
        assert len(indexes.claims_on(bpy.data.objects["Managed"])) == 1


def _ownership_view(binding_ids: list[str], resource_ids: list[str]) -> object:
    """What the ownership index answers, by name: every object's claims, the resources, the unreadable manifests."""
    claims = {
        obj.name: {(c.binding_id, c.destination.name, c.resource_id) for c in indexes.claims_on(obj)}
        for obj in bpy.data.objects
    }
    resources = {(b, r): getattr(indexes.resource(b, r), "name", None) for b in binding_ids for r in resource_ids}
    return claims, resources, len(indexes.unreadable_manifests())


def _entries(*objects: bpy.types.Object) -> Manifest:
    return Manifest({obj.name.lower(): ManifestEntry(obj, ["/World"], "prim", []) for obj in objects})


def test_publications_replace_only_their_share(
    sync: Synchronization, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A publication replaces its destination's share of the index in place; the result is what a rebuild
    # from the records gives, including for a destination a linked copy shares.
    handle = _managed(sync, tmp_path)
    with source_access.binding_state(tmp_path) as scene:
        other = sync.create_file_binding(_scene(), scene.root, name="Other")
    a, b, c = (bpy.data.objects.new(name, None) for name in ("A", "B", "C"))
    indexes.set_manifest(other.binding_id, _entries(a))
    _copy_scene("LINK_COPY")
    ids = [handle.binding_id, other.binding_id]
    names = ["managed", "a", "b", "c"]
    assert _ownership_view(ids, names)  # the index is built

    shares: list[object] = []
    claims_from = ownership.claims_from

    def counted(manifests: list[object]) -> object:
        shares.append(manifests)
        return claims_from(manifests)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr(ownership, "claims_from", counted)
    indexes.set_manifest(handle.binding_id, _entries(bpy.data.objects["Managed"], b))  # the shared destination
    indexes.set_manifest(other.binding_id, _entries(b, c))  # b now claimed twice: ambiguous
    indexes.set_manifest(handle.binding_id, _entries(c))
    in_place = _ownership_view(ids, names)
    assert len(shares) == 3  # one share each, none rebuilt

    indexes.invalidate()
    assert in_place == _ownership_view(ids, names)
    _assert_ownership_agrees()


def test_a_publication_keeps_its_destinations_claimant(sync: Synchronization, tmp_path: Path) -> None:
    # Two identities whose configurations name one destination, as damage leaves them: a publication through
    # the second keeps the claimant a rebuild finds, the first.
    handle = _managed(sync, tmp_path)
    with source_access.binding_state(tmp_path) as scene:
        other = sync.create_file_binding(_scene(), scene.root, name="Other")
    indexes.set_config(other.binding_id, replace(_config(other), destination=bpy.data.collections["Shot"]))
    ids, names = [handle.binding_id, other.binding_id], ["managed", "a"]
    assert _ownership_view(ids, names)  # the index is built
    indexes.set_manifest(other.binding_id, _entries(bpy.data.objects.new("A", None)))
    assert indexes.manifest(handle.binding_id) == indexes.manifest(other.binding_id)  # one destination, one record
    in_place = _ownership_view(ids, names)
    indexes.invalidate()
    assert in_place == _ownership_view(ids, names)


def test_a_removed_scene(sync: Synchronization, tmp_path: Path) -> None:
    other = bpy.data.scenes.new("Other")
    with source_access.binding_state(tmp_path) as scene:
        handle = sync.create_file_binding(other, scene.root)
    assert indexes.binding_ids() == [handle.binding_id]
    address = other.as_pointer()
    bpy.data.scenes.remove(other)
    assert indexes.binding_ids() == []
    # A new scene in the freed memory doesn't pick up the removed one's bindings.
    new = next((s for s in (bpy.data.scenes.new("New") for _ in range(100)) if s.as_pointer() == address), None)
    assert new is not None, "no new scene took the removed one's address"
    assert sync.bindings(new) == []


def test_a_configuration_record_removed_by_hand(sync: Synchronization, tmp_path: Path) -> None:
    # As from the Custom Properties panel with Developer Extras on: no handler, and no scene added or removed.
    handle = _managed(sync, tmp_path)
    assert indexes.binding_ids(_scene()) == [handle.binding_id]
    del _scene()[records.NAMESPACE][bindings.config_key(handle.binding_id)]
    assert indexes.binding_ids(_scene()) == []


def test_a_handler_ahead_of_the_extensions(sync: Synchronization, tmp_path: Path) -> None:
    # Another extension's redo_post handler, running before the extension's, reads the redone data.
    undo.require_global_undo()
    undo.push("base")
    handle = _managed(sync, tmp_path)
    undo.push("create")
    undo.undo()
    assert indexes.binding_ids() == []
    seen: list[list[str]] = []

    def ahead(*_args: object) -> None:
        seen.append(indexes.binding_ids())

    bpy.app.handlers.redo_post.insert(0, ahead)
    try:
        undo.redo()
    finally:
        bpy.app.handlers.redo_post.remove(ahead)
    assert seen == [[handle.binding_id]]


def test_after_save_and_reopen(sync: Synchronization, tmp_path: Path) -> None:
    handle = _managed(sync, tmp_path)
    assert indexes.binding_scene(handle.binding_id) == _scene()
    save_and_reopen(tmp_path / "indexes.blend")
    assert indexes.binding_scene(handle.binding_id) == _scene()
    assert indexes.resource(handle.binding_id, "a") == bpy.data.objects["Managed"]


def test_writes_update_the_state_in_place(
    sync: Synchronization, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A manifest written through the state is answered from memory: no record is read back.
    handle = _managed(sync, tmp_path)
    added = bpy.data.objects.new("Added", None)
    entries = {
        "a": ManifestEntry(bpy.data.objects["Managed"], ["/World"], "prim", []),
        "b": ManifestEntry(added, ["/World/Ref"], "prim", []),
    }
    indexes.set_manifest(handle.binding_id, Manifest(entries))

    def no_reads(*_args: object) -> None:
        raise AssertionError("a record was read back")

    monkeypatch.setattr(records, "read", no_reads)
    assert indexes.claims_on(added) == [Claim(handle.binding_id, bpy.data.collections["Shot"], "b")]
    assert indexes.manifest(handle.binding_id) == Loaded(Manifest(entries), 1)
    assert _config(handle).destination == bpy.data.collections["Shot"]


def test_the_cached_manifest_cant_be_changed_through_a_caller(sync: Synchronization, tmp_path: Path) -> None:
    # The state hands out the manifest it holds, so neither the lists a publisher gave it nor the manifest
    # a lookup returns can change it.
    handle = _managed(sync, tmp_path)
    covers, uses = ["/World"], []
    entries = {"a": ManifestEntry(bpy.data.objects["Managed"], covers, "prim", uses)}
    indexes.set_manifest(handle.binding_id, Manifest(entries))
    covers.append("/Elsewhere")
    uses.append("a")
    entries["b"] = ManifestEntry(bpy.data.objects.new("B", None), ["/World/B"], "prim", [])
    found = indexes.manifest(handle.binding_id)
    assert isinstance(found, Loaded)
    assert found == ownership.read_manifest(bpy.data.collections["Shot"])
    with pytest.raises(TypeError):
        found.record.entries["c"] = entries["b"]  # ty: ignore[invalid-assignment] - the point: it's read-only
    with pytest.raises(AttributeError):
        found.record.entries["a"].covers.append("/Elsewhere")  # ty: ignore[unresolved-attribute]
    with pytest.raises(AttributeError):
        found.record.entries["a"].uses.append("a")  # ty: ignore[unresolved-attribute]


def _file_data() -> dict[tuple[str, str], object]:
    """The IDs a binding's writes make or change, with their records: scenes, collections, and texts."""
    ids = [*bpy.data.scenes, *bpy.data.collections, *bpy.data.texts]
    return {(type(id_).__name__, id_.name): {k: records.stored(id_, k) for k in records.keys(id_)} for id_ in ids}


def test_creation_needs_the_extension_registered(tmp_path: Path) -> None:
    # Without the handlers, a cached configuration would outlive an undo that reverted it. The check
    # comes first: a binding made anyway would be in the file, and found at the next load.
    with source_access.binding_state(tmp_path) as scene:
        before = _file_data()
        with pytest.raises(indexes.NotTracking):
            Synchronization().create_file_binding(_scene(), scene.root)
        with pytest.raises(indexes.NotTracking):
            Synchronization().create_attached_binding(_scene(), "shot")
    assert _file_data() == before


def test_writes_need_the_extension_registered(sync: Synchronization, tmp_path: Path) -> None:
    handle = _managed(sync, tmp_path)
    sync.create_attached_binding(_scene(), "shot")
    addon.unregister()
    before = _file_data()
    with pytest.raises(indexes.NotTracking):
        handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    with pytest.raises(indexes.NotTracking):
        sync.attach("shot", Usd.Stage.CreateInMemory(), confirm=True)
    with pytest.raises(indexes.NotTracking):
        indexes.set_manifest(handle.binding_id, Manifest({}))
    assert _file_data() == before


def test_a_struct_inside_a_datablock_is_not_invalidated_by_undo() -> None:
    # Why the state holds only ID references. A modifier held across undo of a step that changed its
    # object isn't invalidated: it names freed memory, so it's compared by address here, never read.
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
