"""The bindings' in-memory state returns current datablocks or nothing, never a removed one (UNDO-07).

lifecycle.md#undo-and-runtime-state. On F-BINDING-STATE, with the extension registered, whose
load, undo, and redo handlers drop the state; removals no handler announces are caught by the
checks on each hit.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator
from dataclasses import replace
from typing import TYPE_CHECKING, override

import bpy
import pytest
from pxr import Usd

from fixtures import source_access
from proscenium import addon, runtime
from proscenium.api.bindings import BindingHandle, Bindings
from proscenium.core.source_access import PayloadPolicy
from proscenium.persistence import binding_records, manifests, records
from proscenium.persistence.binding_records import BindingConfig
from proscenium.persistence.manifests import Manifest, ManifestEntry
from proscenium.persistence.records import Loaded, RefusedRecord
from proscenium.runtime import Claim, ownership_index, state
from support import ownership as oracle
from support import undo
from support.blend import save_and_reopen

if TYPE_CHECKING:
    from pathlib import Path


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _managed(bindings: Bindings, tmp_path: Path) -> BindingHandle:
    """A binding on F-BINDING-STATE whose destination holds one managed object, resource "a"."""
    with source_access.binding_state(tmp_path) as scene:
        handle = bindings.create_file_binding(_scene(), scene.root, name="Shot")
    obj = bpy.data.objects.new("Managed", None)
    bpy.data.collections["Shot"].objects.link(obj)
    runtime.set_manifest(handle.binding_id, Manifest({"a": ManifestEntry(obj, ["/World"], "prim", [])}))
    return handle


def _config(handle: BindingHandle) -> BindingConfig:
    config = runtime.config(handle.binding_id)
    assert isinstance(config, BindingConfig)
    return config


def test_undo_and_redo_of_creation(bindings: Bindings, tmp_path: Path) -> None:
    # UNDO-07: after undo the binding isn't found; after redo, its scene is the current one.
    undo.require_global_undo()
    undo.push("base")
    handle = _managed(bindings, tmp_path)
    assert runtime.binding_scene(handle.binding_id) == _scene()
    undo.push("create")
    undo.undo()
    assert runtime.binding_scene(handle.binding_id) is None
    assert runtime.resource(handle.binding_id, "a") is None
    undo.redo()
    assert runtime.binding_scene(handle.binding_id) == _scene()
    assert runtime.resource(handle.binding_id, "a") == bpy.data.objects["Managed"]


def test_undo_of_a_change_to_managed_content(bindings: Bindings, tmp_path: Path) -> None:
    # Undo re-reads what the step changed, as a synchronization changes managed content.
    undo.require_global_undo()
    handle = _managed(bindings, tmp_path)
    assert runtime.resource(handle.binding_id, "a") == bpy.data.objects["Managed"]
    undo.push("base")
    bpy.data.objects["Managed"].location.x = 5.0
    undo.push("sync")
    undo.undo()
    current = bpy.data.objects["Managed"]
    assert runtime.resource(handle.binding_id, "a") == current
    assert runtime.claims_on(current) == [Claim(handle.binding_id, bpy.data.collections["Shot"], "a")]


def test_undo_reverts_a_cached_configuration(bindings: Bindings, tmp_path: Path) -> None:
    # The state caches the decoded configuration; undo restores the record, and the handler drops the cache.
    undo.require_global_undo()
    handle = _managed(bindings, tmp_path)
    undo.push("base")
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    assert _config(handle).payload_policy is PayloadPolicy.LOAD_NONE
    undo.push("settings")
    undo.undo()
    assert _config(handle).payload_policy is PayloadPolicy.LOAD_ALL


def test_removed_managed_content(bindings: Bindings, tmp_path: Path) -> None:
    # No handler announces it: the check on the hit does.
    handle = _managed(bindings, tmp_path)
    assert runtime.resource(handle.binding_id, "a") is not None
    bpy.data.objects.remove(bpy.data.objects["Managed"])
    assert runtime.resource(handle.binding_id, "a") is None


def test_a_removed_datablock_leaves_the_cached_manifest(bindings: Bindings, tmp_path: Path) -> None:
    # The manifest in memory names the datablock; after the removal it shows what the record does.
    handle = _managed(bindings, tmp_path)
    assert runtime.manifest(handle.binding_id) is not None
    bpy.data.objects.remove(bpy.data.objects["Managed"])
    found = runtime.manifest(handle.binding_id)
    assert isinstance(found, Loaded)
    assert found.record.entries["a"].datablock is None  # Blender cleared the stored pointer
    assert found == manifests.read_manifest(bpy.data.collections["Shot"])


def _two_managed(bindings: Bindings, tmp_path: Path) -> tuple[list[str], list[str]]:
    """_managed's binding, and Other managing two objects, A and B; with the index built. Their identifiers,
    and the resource identities to look up."""
    handle = _managed(bindings, tmp_path)
    with source_access.binding_state(tmp_path) as scene:
        other = bindings.create_file_binding(_scene(), scene.root, name="Other")
    runtime.set_manifest(other.binding_id, _entries(*(bpy.data.objects.new(name, None) for name in ("A", "B"))))
    ids, names = [handle.binding_id, other.binding_id], ["managed", "a", "b"]
    assert _ownership_view(ids, names)
    return ids, names


def _counted_reads(monkeypatch: pytest.MonkeyPatch) -> tuple[list[tuple[str, str]], list[str]]:
    """Every record read from here on, as (ID name, key), and every share of the ownership index built."""
    reads: list[tuple[str, str]] = []
    read = records.read

    def counted_read(id_: bpy.types.ID, key: str, schema: object) -> object:
        reads.append((id_.name, key))
        return read(id_, key, schema)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr(records, "read", counted_read)
    return reads, _counted_shares(monkeypatch)


def _counted_shares(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The destination of every share of the ownership index built from here on, by name."""
    shares: list[str] = []
    add_share = ownership_index._add_share  # noqa: SLF001 - the cost under test is how many shares are built

    def counted(index: object, claimant: str, destination: bpy.types.Collection, manifest: object) -> None:
        shares.append(destination.name)
        add_share(index, claimant, destination, manifest)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr(ownership_index, "_add_share", counted)
    return shares


@pytest.mark.parametrize("lookup", ["resource", "manifest"])
def test_a_removed_datablock_rereads_only_its_manifest(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lookup: str
) -> None:
    # The cost of a removal doesn't grow with the rest of the file: the other binding's share and every
    # configuration stay, and the result is what a rebuild from the records gives.
    ids, names = _two_managed(bindings, tmp_path)
    other = ids[1]
    rebuilds = runtime.rebuild_count()
    reads, shares = _counted_reads(monkeypatch)
    bpy.data.objects.remove(bpy.data.objects["A"])
    if lookup == "resource":
        assert runtime.resource(other, "a") is None
    else:
        found = runtime.manifest(other)
        assert isinstance(found, Loaded)
        assert found.record.entries["a"].datablock is None
    assert reads == [("Other", manifests.MANIFEST_KEY)]
    assert runtime.rebuild_count() == rebuilds
    assert runtime.resource(other, "b") == bpy.data.objects["B"]
    in_place = _ownership_view(ids, names)
    assert reads == [("Other", manifests.MANIFEST_KEY)]  # the share replaced holds no removed datablock
    assert len(shares) == 1  # Other's, replaced; the index isn't rebuilt
    runtime.invalidate()
    assert in_place == _ownership_view(ids, names)


def _entry(datablock: bpy.types.ID, uses: list[str] | None = None) -> ManifestEntry:
    return ManifestEntry(datablock, ["/World"], "prim", uses or [])


def test_an_update_writes_and_indexes_only_what_changes(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Phase 2 refreshes change some resources; an update costs those, and its result is what a rebuild gives.
    ids, names = _two_managed(bindings, tmp_path)
    other, destination = ids[1], bpy.data.collections["Other"]
    a, b = bpy.data.objects["A"], bpy.data.objects["B"]
    c, d = bpy.data.objects.new("C", None), bpy.data.objects.new("D", None)
    # An entry stored but not in the state: a whole write would drop it, so its staying shows none happened.
    destination[records.NAMESPACE][manifests.MANIFEST_KEY]["entries"]["marker"] = {
        "datablock": None,
        "covers": [],
        "role": "marker",
        "uses": [],
    }
    rebuilds = runtime.rebuild_count()
    reads, shares = _counted_reads(monkeypatch)
    # b's datablock moves to c, and d uses c.
    runtime.set_manifest_entries(other, {"b": _entry(c), "c": _entry(b), "d": _entry(d, ["c"])}, ["a"])
    names += ["c", "d"]
    in_place = _ownership_view(ids, names)
    assert (reads, shares, runtime.rebuild_count()) == ([], [], rebuilds)  # nothing reread or rebuilt
    assert [runtime.resource(other, r) for r in ("a", "b", "c", "d")] == [None, c, b, d]
    assert runtime.claims_on(a) == []
    assert runtime.claims_on(b) == [Claim(other, destination, "c")]
    entries = destination[records.NAMESPACE][manifests.MANIFEST_KEY]["entries"]
    assert "marker" in entries
    del entries["marker"]
    assert runtime.manifest(other) == manifests.read_manifest(destination)
    runtime.invalidate()
    assert in_place == _ownership_view(ids, names)


@pytest.mark.parametrize("first_removed", ["Other", "Shot"])
def test_a_datablock_claimed_twice_and_once_again(bindings: Bindings, tmp_path: Path, first_removed: str) -> None:
    # Ambiguity is rare, so a datablock claimed once is held as its one claim, not a collection of them.
    ids, names = _two_managed(bindings, tmp_path)
    handle, other = ids
    a = bpy.data.objects["A"]
    by_name = {
        "Other": Claim(other, bpy.data.collections["Other"], "a"),
        "Shot": Claim(handle, bpy.data.collections["Shot"], "x"),
    }
    runtime.set_manifest_entries(handle, {"x": _entry(a)})
    assert set(runtime.claims_on(a)) == set(by_name.values())
    in_place = _ownership_view(ids, [*names, "x"])
    runtime.invalidate()
    assert in_place == _ownership_view(ids, [*names, "x"])
    if first_removed == "Other":
        runtime.set_manifest_entries(other, {}, ["a"])
    else:
        runtime.set_manifest_entries(handle, {}, ["x"])
    [kept] = [claim for name, claim in by_name.items() if name != first_removed]
    assert runtime.claims_on(a) == [kept]
    found = state._state  # noqa: SLF001 - how a claim is held is what saves memory
    assert found is not None and found.ownership is not None
    assert found.ownership.claims[a.session_uid] == kept
    in_place = _ownership_view(ids, [*names, "x"])
    runtime.invalidate()
    assert in_place == _ownership_view(ids, [*names, "x"])


class _CountedRemovals(Collection[str]):
    """A caller's removals, counting the membership tests made on them."""

    items: list[str]
    tests: int

    def __init__(self, items: list[str]) -> None:
        self.items = items
        self.tests = 0

    @override
    def __contains__(self, item: object) -> bool:
        self.tests += 1
        return item in self.items

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self.items)

    @override
    def __len__(self) -> int:
        return len(self.items)


def test_removals_are_tested_as_a_set(bindings: Bindings, tmp_path: Path) -> None:
    # Each entry and each use is tested against the removals: a caller's list would make every test a search.
    ids, names = _two_managed(bindings, tmp_path)
    other = ids[1]
    current = runtime.manifest(other)
    assert isinstance(current, Loaded)
    direct = _CountedRemovals(["a"])
    current.record.updated({}, direct, lambda _uid: None)
    through_the_state = _CountedRemovals(["a", "a"])  # a duplicate, too
    runtime.set_manifest_entries(other, {}, through_the_state)
    assert (direct.tests, through_the_state.tests) == (0, 0)
    assert runtime.manifest(other) == manifests.read_manifest(bpy.data.collections["Other"])
    # Iterated once: an iterator, which the type rules out, still reaches the record and the index alike.
    runtime.set_manifest_entries(other, {}, iter(["b"]))  # ty: ignore[invalid-argument-type]
    assert runtime.manifest(other) == manifests.read_manifest(bpy.data.collections["Other"])
    in_place = _ownership_view(ids, names)
    runtime.invalidate()
    assert in_place == _ownership_view(ids, names)


def test_an_empty_update_writes_nothing(bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A no-op refresh performs no Blender writes (incremental.md#affected-content).
    handle = _managed(bindings, tmp_path)

    def no_writes(*_args: object) -> None:
        raise AssertionError("a record was written")

    monkeypatch.setattr(records, "write", no_writes)
    monkeypatch.setattr(records, "write_items", no_writes)
    runtime.set_manifest_entries(handle.binding_id, {}, [])


def test_an_update_to_a_binding_without_a_manifest(bindings: Bindings, tmp_path: Path) -> None:
    with source_access.binding_state(tmp_path) as scene:
        handle = bindings.create_file_binding(_scene(), scene.root, name="Shot")
    assert runtime.manifest(handle.binding_id) is None
    obj = bpy.data.objects.new("Managed", None)
    runtime.set_manifest_entries(handle.binding_id, {"a": _entry(obj)})
    assert runtime.manifest(handle.binding_id) == Loaded(Manifest({"a": _entry(obj)}), 1)
    assert runtime.manifest(handle.binding_id) == manifests.read_manifest(bpy.data.collections["Shot"])
    assert runtime.resource(handle.binding_id, "a") == obj


@pytest.mark.parametrize("removed", [["a"], []])
def test_an_update_after_a_removal(bindings: Bindings, tmp_path: Path, removed: list[str]) -> None:
    # The removed datablock's entry, which Blender cleared, is removed by the update or carried into its result.
    ids, names = _two_managed(bindings, tmp_path)
    other = ids[1]
    bpy.data.objects.remove(bpy.data.objects["A"])
    replacement = bpy.data.objects.new("Replacement", None)
    runtime.set_manifest_entries(other, {"b": _entry(replacement)}, removed)
    assert runtime.manifest(other) == manifests.read_manifest(bpy.data.collections["Other"])
    in_place = _ownership_view(ids, names)
    assert runtime.resource(other, "b") == replacement
    runtime.invalidate()
    assert in_place == _ownership_view(ids, names)


def test_a_new_datablock_at_a_removed_ones_address_is_unmanaged(bindings: Bindings, tmp_path: Path) -> None:
    handle = _managed(bindings, tmp_path)
    removed = bpy.data.objects["Managed"]
    assert runtime.claims_on(removed) == [Claim(handle.binding_id, bpy.data.collections["Shot"], "a")]
    address = removed.as_pointer()
    bpy.data.objects.remove(removed)
    # The case under test is a new object in the freed memory; the allocator may hand it out a few allocations later.
    new = next((o for o in (bpy.data.objects.new("New", None) for _ in range(100)) if o.as_pointer() == address), None)
    assert new is not None, "no new object took the removed one's address"
    assert runtime.claims_on(new) == []


def test_a_removed_destination(bindings: Bindings, tmp_path: Path) -> None:
    handle = _managed(bindings, tmp_path)
    obj = bpy.data.objects["Managed"]
    assert runtime.claims_on(obj)
    bpy.data.collections.remove(bpy.data.collections["Shot"])
    assert runtime.resource(handle.binding_id, "a") is None  # though the object it named remains
    assert runtime.manifest(handle.binding_id) is None
    assert runtime.claims_on(obj) == []  # the manifest went with its collection
    assert _config(handle).destination is None  # Blender cleared the pointer, and the state was rebuilt


@pytest.mark.parametrize("asked", ["claims", "update"])
def test_a_destination_removed_before_the_ownership_index_is_built(
    bindings: Bindings, tmp_path: Path, asked: str
) -> None:
    # The state is built without the index; building it then finds the removed destination and rebuilds.
    ids, _ = _two_managed(bindings, tmp_path)
    runtime.invalidate()
    assert runtime.binding_ids() == ids
    bpy.data.collections.remove(bpy.data.collections["Shot"])
    if asked == "claims":
        assert runtime.claims_on(bpy.data.objects["Managed"]) == []
    else:
        runtime.set_manifest_entries(ids[1], {"c": _entry(bpy.data.objects.new("C", None))})
        assert runtime.resource(ids[1], "c") == bpy.data.objects["C"]
    assert [c.binding_id for c in runtime.claims_on(bpy.data.objects["A"])] == [ids[1]]


def test_a_destination_change_after_another_bindings_destination_was_removed(
    bindings: Bindings, tmp_path: Path
) -> None:
    # The change rebuilds the map of destinations from the configurations in memory, one of which names a
    # removed collection; that binding's next check rebuilds the state.
    ids, _ = _two_managed(bindings, tmp_path)
    handle = BindingHandle(ids[0])
    bpy.data.collections.remove(bpy.data.collections["Other"])
    repaired = bpy.data.collections.new("Repaired")
    _move_destination(ids[0], bpy.data.collections["Shot"], repaired)
    runtime.set_config(ids[0], replace(_config(handle), destination=repaired))
    assert _config(handle).destination == repaired
    assert _config(BindingHandle(ids[1])).destination is None


def _move_destination(binding_id: str, old: bpy.types.Collection, new: bpy.types.Collection) -> None:
    """What a repair moves with a binding's destination, so the old one isn't left as a copy: its tag, and the
    index entry. The configuration is the caller's."""
    tag = records.read(old, binding_records.TAG_KEY, binding_records.TAG)
    assert isinstance(tag, Loaded)
    records.write(new, binding_records.TAG_KEY, binding_records.TAG, tag.record)
    del old[records.NAMESPACE][binding_records.TAG_KEY]
    [text] = binding_records.index_texts()
    index = records.read(text, binding_records.INDEX_KEY, binding_records.INDEX)
    assert isinstance(index, Loaded)
    destinations = index.record.destinations | {binding_id: new}
    records.write(text, binding_records.INDEX_KEY, binding_records.INDEX, binding_records.BindingIndex(destinations))


def test_a_resource_is_read_through_its_bindings_manifest_alone(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # resource() doesn't build the ownership index, which reads every binding's manifest.
    ids, _ = _two_managed(bindings, tmp_path)
    runtime.invalidate()
    reads, shares = _counted_reads(monkeypatch)
    assert runtime.resource(ids[1], "a") == bpy.data.objects["A"]
    assert [read for read in reads if read[1] == manifests.MANIFEST_KEY] == [("Other", manifests.MANIFEST_KEY)]
    assert shares == []


def _copy_scene(kind: str) -> bpy.types.Scene:
    assert bpy.context.scene == _scene()  # the scene the operator copies
    bpy.ops.scene.new(type=kind)  # ty: ignore[invalid-argument-type] - stubs type the enum as a literal union
    (copy,) = (scene for scene in bpy.data.scenes if scene != _scene())
    return copy


def _assert_ownership_agrees() -> None:
    # The state's claims are the oracle's, read from the records now, for every object.
    expected, _ = oracle.claims()
    for obj in bpy.data.objects:
        assert set(runtime.claims_on(obj)) == set(expected.get(obj, []))


@pytest.mark.parametrize("kind", ["FULL_COPY", "LINK_COPY"])
def test_a_scene_copy_made_after_the_state_was_built(bindings: Bindings, tmp_path: Path, kind: str) -> None:
    # No handler announces a new scene. The copy is a candidate of the binding's identity, which the
    # index names the original's destination, so the original stays canonical and the copy is reported,
    # not listed on its scene (source-access.md#copied-bindings); its manifest counts as the oracle counts it.
    handle = _managed(bindings, tmp_path)
    assert runtime.claims_on(bpy.data.objects["Managed"])  # the state, ownership included, is built
    copy = _copy_scene(kind)
    assert bindings.in_scene(copy) == []
    assert bindings.in_scene(_scene()) == [handle]
    [copied] = bindings.copied()
    assert [(c.scene, c.canonical) for c in copied.candidates] == [("Scene", True), (copy.name, False)]
    assert runtime.binding_scene(handle.binding_id) == _scene()  # lookups use the canonical candidate
    _assert_ownership_agrees()
    if kind == "FULL_COPY":
        (copied,) = (obj for obj in bpy.data.objects if obj.name != "Managed")
        assert [c.destination for c in runtime.claims_on(copied)] == [copy.collection.children[0]]
    else:  # the copy shares the destination, whose manifest counts once
        assert len(runtime.claims_on(bpy.data.objects["Managed"])) == 1


def _ownership_view(binding_ids: list[str], resource_ids: list[str]) -> object:
    """What the ownership index answers, by name: every object's claims, the resources, the unreadable manifests."""
    claims = {
        obj.name: {(c.binding_id, c.destination.name, c.resource_id) for c in runtime.claims_on(obj)}
        for obj in bpy.data.objects
    }
    resources = {(b, r): getattr(runtime.resource(b, r), "name", None) for b in binding_ids for r in resource_ids}
    return claims, resources, len(runtime.unreadable_manifests())


def _entries(*objects: bpy.types.Object) -> Manifest:
    return Manifest({obj.name.lower(): ManifestEntry(obj, ["/World"], "prim", []) for obj in objects})


def test_publications_replace_only_their_share(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A publication replaces its destination's share of the index in place; the result is what a rebuild
    # from the records gives, including for a destination a linked copy shares.
    handle = _managed(bindings, tmp_path)
    with source_access.binding_state(tmp_path) as scene:
        other = bindings.create_file_binding(_scene(), scene.root, name="Other")
    a, b, c = (bpy.data.objects.new(name, None) for name in ("A", "B", "C"))
    runtime.set_manifest(other.binding_id, _entries(a))
    _copy_scene("LINK_COPY")
    ids = [handle.binding_id, other.binding_id]
    names = ["managed", "a", "b", "c"]
    assert _ownership_view(ids, names)  # the index is built

    shares = _counted_shares(monkeypatch)
    runtime.set_manifest(handle.binding_id, _entries(bpy.data.objects["Managed"], b))  # the shared destination
    runtime.set_manifest(other.binding_id, _entries(b, c))  # b now claimed twice: ambiguous
    runtime.set_manifest(handle.binding_id, _entries(c))
    in_place = _ownership_view(ids, names)
    assert len(shares) == 3  # one share each, none rebuilt

    runtime.invalidate()
    assert in_place == _ownership_view(ids, names)
    _assert_ownership_agrees()


def test_a_publication_keeps_its_destinations_claimant(bindings: Bindings, tmp_path: Path) -> None:
    # Two identities whose configurations name one destination, as damage leaves them: a publication through
    # the second keeps the claimant a rebuild finds, the first. The second's own destination is removed, so
    # it has no copy there and stays unique.
    handle = _managed(bindings, tmp_path)
    with source_access.binding_state(tmp_path) as scene:
        other = bindings.create_file_binding(_scene(), scene.root, name="Other")
    bpy.data.collections.remove(bpy.data.collections["Other"])
    runtime.set_config(other.binding_id, replace(_config(other), destination=bpy.data.collections["Shot"]))
    ids, names = [handle.binding_id, other.binding_id], ["managed", "a"]
    assert _ownership_view(ids, names)  # the index is built
    runtime.set_manifest(other.binding_id, _entries(bpy.data.objects.new("A", None)))
    assert runtime.manifest(handle.binding_id) == runtime.manifest(other.binding_id)  # one destination, one record
    # Each identity's resources are what its manifest names, though the claims name the first.
    assert runtime.resource(handle.binding_id, "a") == runtime.resource(other.binding_id, "a") == bpy.data.objects["A"]
    assert [c.binding_id for c in runtime.claims_on(bpy.data.objects["A"])] == [handle.binding_id]
    in_place = _ownership_view(ids, names)
    runtime.invalidate()
    assert in_place == _ownership_view(ids, names)


def test_a_removed_scene(bindings: Bindings, tmp_path: Path) -> None:
    other = bpy.data.scenes.new("Other")
    with source_access.binding_state(tmp_path) as scene:
        handle = bindings.create_file_binding(other, scene.root)
    assert runtime.binding_ids() == [handle.binding_id]
    address = other.as_pointer()
    bpy.data.scenes.remove(other)
    assert runtime.binding_ids() == []
    # A new scene in the freed memory doesn't pick up the removed one's bindings.
    new = next((s for s in (bpy.data.scenes.new("New") for _ in range(100)) if s.as_pointer() == address), None)
    assert new is not None, "no new scene took the removed one's address"
    assert bindings.in_scene(new) == []


def test_listing_a_scene_checks_only_its_bindings(bindings: Bindings, tmp_path: Path) -> None:
    # A binding on another scene can't change the answer; one on the scene listed can.
    other_scene = bpy.data.scenes.new("Other")
    with source_access.binding_state(tmp_path) as scene:
        elsewhere = bindings.create_file_binding(other_scene, scene.root, name="Elsewhere")
        here = bindings.create_file_binding(_scene(), scene.root, name="Here")
    assert bindings.in_scene(_scene()) == [here]
    bpy.data.collections.remove(bpy.data.collections["Elsewhere"])
    rebuilds = runtime.rebuild_count()
    assert bindings.in_scene(_scene()) == [here]
    assert runtime.rebuild_count() == rebuilds  # not checked, so nothing found to rebuild
    assert runtime.binding_ids() == [elsewhere.binding_id, here.binding_id]
    assert runtime.rebuild_count() > rebuilds  # listing every binding checks it
    assert _config(elsewhere).destination is None
    bpy.data.collections.remove(bpy.data.collections["Here"])
    rebuilds = runtime.rebuild_count()
    assert bindings.in_scene(_scene()) == [here]
    assert runtime.rebuild_count() > rebuilds
    assert _config(here).destination is None


def test_the_bindings_attached_with_a_key(bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # One pass over the state: the scenes are compared once, and each binding's configuration checked.
    other_scene = bpy.data.scenes.new("Other")
    a = bindings.create_attached_binding(_scene(), "shot", name="A")
    b = bindings.create_attached_binding(other_scene, "shot", name="B")
    bindings.create_attached_binding(_scene(), "other", name="C")
    unreadable = bindings.create_attached_binding(_scene(), "shot", name="D")
    with source_access.binding_state(tmp_path) as scene:
        bindings.create_file_binding(_scene(), scene.root, name="F")
    _scene()[records.NAMESPACE][binding_records.config_key(unreadable.binding_id)][records.VERSION_KEY] = 2
    runtime.invalidate()  # the record changed behind the state, as a load or undo changes it
    current, calls = state.current_state, []  # the cost under test is one comparison of the scenes

    def counted() -> object:
        calls.append(1)
        return current()

    monkeypatch.setattr(state, "current_state", counted)
    assert {(binding_id, config.source_key) for binding_id, config in runtime.attached_with_key("shot")} == {
        (a.binding_id, "shot"),
        (b.binding_id, "shot"),
    }
    assert len(calls) == 1
    bpy.data.collections.remove(bpy.data.collections["A"])
    found = dict(runtime.attached_with_key("shot"))
    assert found[a.binding_id].destination is None  # the check found the removed destination; the state was rebuilt


def test_every_bindings_configuration(bindings: Bindings, tmp_path: Path) -> None:
    # As config() gives each: the first candidate's, or why it can't be read, checked.
    readable = bindings.create_attached_binding(_scene(), "shot", name="A")
    unreadable = bindings.create_attached_binding(_scene(), "shot", name="B")
    _scene()[records.NAMESPACE][binding_records.config_key(unreadable.binding_id)][records.VERSION_KEY] = 2
    runtime.invalidate()  # the record changed behind the state, as a load or undo changes it
    found = runtime.configs()
    assert found == {
        readable.binding_id: runtime.config(readable.binding_id),
        unreadable.binding_id: found[unreadable.binding_id],
    }
    assert isinstance(found[unreadable.binding_id], RefusedRecord)
    bpy.data.collections.remove(bpy.data.collections["A"])
    config = runtime.configs()[readable.binding_id]
    assert isinstance(config, binding_records.BindingConfig)
    assert config.destination is None  # the check found the removed destination; the state was rebuilt


def test_a_configuration_record_removed_by_hand(bindings: Bindings, tmp_path: Path) -> None:
    # As from the Custom Properties panel with Developer Extras on: no handler, and no scene added or removed.
    handle = _managed(bindings, tmp_path)
    assert runtime.binding_ids(_scene()) == [handle.binding_id]
    del _scene()[records.NAMESPACE][binding_records.config_key(handle.binding_id)]
    assert runtime.binding_ids(_scene()) == []


def test_a_handler_ahead_of_the_extensions(bindings: Bindings, tmp_path: Path) -> None:
    # Another extension's redo_post handler, running before the extension's, reads the redone data.
    undo.require_global_undo()
    undo.push("base")
    handle = _managed(bindings, tmp_path)
    undo.push("create")
    undo.undo()
    assert runtime.binding_ids() == []
    seen: list[list[str]] = []

    def ahead(*_args: object) -> None:
        seen.append(runtime.binding_ids())

    bpy.app.handlers.redo_post.insert(0, ahead)
    try:
        undo.redo()
    finally:
        bpy.app.handlers.redo_post.remove(ahead)
    assert seen == [[handle.binding_id]]


def test_after_save_and_reopen(bindings: Bindings, tmp_path: Path) -> None:
    handle = _managed(bindings, tmp_path)
    assert runtime.binding_scene(handle.binding_id) == _scene()
    save_and_reopen(tmp_path / "indexes.blend")
    assert runtime.binding_scene(handle.binding_id) == _scene()
    assert runtime.resource(handle.binding_id, "a") == bpy.data.objects["Managed"]


def test_writes_update_the_state_in_place(bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A manifest written through the state is answered from memory: no record is read back.
    handle = _managed(bindings, tmp_path)
    added = bpy.data.objects.new("Added", None)
    entries = {
        "a": ManifestEntry(bpy.data.objects["Managed"], ["/World"], "prim", []),
        "b": ManifestEntry(added, ["/World/Ref"], "prim", []),
    }
    runtime.set_manifest(handle.binding_id, Manifest(entries))

    def no_reads(*_args: object) -> None:
        raise AssertionError("a record was read back")

    monkeypatch.setattr(records, "read", no_reads)
    assert runtime.claims_on(added) == [Claim(handle.binding_id, bpy.data.collections["Shot"], "b")]
    assert runtime.manifest(handle.binding_id) == Loaded(Manifest(entries), 1)
    assert _config(handle).destination == bpy.data.collections["Shot"]


def test_the_cached_manifest_cant_be_changed_through_a_caller(bindings: Bindings, tmp_path: Path) -> None:
    # The state hands out the manifest it holds, so neither the lists a publisher gave it nor the manifest
    # a lookup returns can change it.
    handle = _managed(bindings, tmp_path)
    covers, uses = ["/World"], []
    entries = {"a": ManifestEntry(bpy.data.objects["Managed"], covers, "prim", uses)}
    runtime.set_manifest(handle.binding_id, Manifest(entries))
    covers.append("/Elsewhere")
    uses.append("a")
    entries["b"] = ManifestEntry(bpy.data.objects.new("B", None), ["/World/B"], "prim", [])
    found = runtime.manifest(handle.binding_id)
    assert isinstance(found, Loaded)
    assert found == manifests.read_manifest(bpy.data.collections["Shot"])
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
        with pytest.raises(runtime.NotRegisteredError):
            Bindings().create_file_binding(_scene(), scene.root)
        with pytest.raises(runtime.NotRegisteredError):
            Bindings().create_attached_binding(_scene(), "shot")
    assert _file_data() == before


def test_writes_need_the_extension_registered(bindings: Bindings, tmp_path: Path) -> None:
    handle = _managed(bindings, tmp_path)
    bindings.create_attached_binding(_scene(), "shot")
    addon.unregister()
    before = _file_data()
    with pytest.raises(runtime.NotRegisteredError):
        handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    with pytest.raises(runtime.NotRegisteredError):
        bindings.attach("shot", Usd.Stage.CreateInMemory(), confirm=True)
    with pytest.raises(runtime.NotRegisteredError):
        runtime.set_manifest(handle.binding_id, Manifest({}))
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
