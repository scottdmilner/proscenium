"""Copied-binding detection on F-OWNERSHIP-AMBIGUITY (source-access.md#copied-bindings, #canonical-candidate).

Each route runs on a published binding, and the test checks what the synchronization API reports against
the outcome the fixture derives from the canonical-candidate rule: after a synchronization, which looks
for copies first, again after the bindings' state is rebuilt, and again after save and reopen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import copies
from proscenium import runtime
from proscenium.api.synchronization import BindingDisabledError, BindingHandle, Category, ResultState, Synchronization
from proscenium.core.source_access import PayloadPolicy
from proscenium.persistence import bindings, records
from proscenium.persistence.manifests import Manifest, ManifestEntry
from proscenium.persistence.records import Loaded
from support import copies as routes
from support import ownership as oracle
from support.blend import save_and_reopen
from support.usd import open_fresh

if TYPE_CHECKING:
    from pathlib import Path

    from fixtures.copies import Outcome
    from proscenium.runtime.candidates import CopiedBinding


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _published(sync: Synchronization, root: Path) -> BindingHandle:
    """The binding every route copies: "Shot" on "Scene", its manifest naming "Managed"."""
    handle = sync.create_file_binding(_scene(), root, name="Shot")
    obj = bpy.data.objects.new("Managed", None)
    bpy.data.collections["Shot"].objects.link(obj)
    runtime.set_manifest(handle.binding_id, Manifest({"a": ManifestEntry(obj, ["/World"], "prim", [])}))
    return handle


def _index_entry() -> bpy.types.Collection | None:
    [text] = bindings.index_texts()
    index = records.read(text, bindings.INDEX_KEY, bindings.INDEX)
    assert isinstance(index, Loaded)
    [destination] = index.record.destinations.values()
    return destination


def _assert_ownership_agrees() -> None:
    # The state's claims are the oracle's for every object: a copy's manifest counts, a record's or a tagged
    # collection's that no record names, so content a copy names is ambiguous (OWN-16).
    expected, _ = oracle.claims()
    for obj in bpy.data.objects:
        assert set(runtime.claims_on(obj)) == set(expected.get(obj, []))


def _check(sync: Synchronization, handle: BindingHandle, outcome: Outcome) -> list[CopiedBinding]:
    """What the API reports for the binding, against the outcome; returns the report."""
    result = handle.synchronize(0)  # looks for copies first (COPY-18)
    reported = sync.copied_bindings()
    if outcome.reason is copies.Reason.UNIQUE:
        assert reported == []  # COPY-14: nothing to report for a unique identity
        assert result.state is ResultState.SUCCESS
        assert sync.bindings(_scene()) == [handle]
        return reported
    # COPY-01, COPY-13: every candidate found, records first, in the order found: the original's first.
    [report] = reported
    assert (report.binding_id, report.reason, len(report.candidates)) == (
        handle.binding_id,
        outcome.reason,
        outcome.candidates,
    )
    scenes = {c.scene for c in report.candidates if c.scene is not None}
    if outcome.canonical:
        # COPY-09, COPY-10, COPY-15: the original is canonical, its scene alone lists it, and lookups reach it.
        assert [c.canonical for c in report.candidates] == [True] + [False] * (outcome.candidates - 1)
        assert (report.candidates[0].scene, report.candidates[0].destination) == ("Scene", "Shot")
        assert result.state is ResultState.SUCCESS
        assert runtime.binding_scene(handle.binding_id) == _scene()
        for name in scenes:
            assert sync.bindings(bpy.data.scenes[name]) == ([handle] if name == "Scene" else [])
    else:
        # COPY-02, COPY-11, COPY-16: every candidate disabled; listed on each scene with one; refused.
        assert not any(c.canonical for c in report.candidates)
        for name in scenes:
            assert sync.bindings(bpy.data.scenes[name]) == [handle]
        for refused in (result, handle.reload(), handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)):
            assert refused.state is ResultState.FATAL_FAILURE
            assert [d.category for d in refused.diagnostics] == [Category.COPIED_BINDING]
            assert all(
                c.destination is None or c.destination in refused.diagnostics[0].message for c in report.candidates
            )
        assert handle.binding_id not in sync.stages
        with pytest.raises(BindingDisabledError):
            handle.requested_settings()
        assert handle.live_stage() is None
    return reported


@pytest.mark.parametrize("route", list(copies.ROUTES))
def test_route(sync: Synchronization, tmp_path: Path, route: str) -> None:
    with copies.ownership_ambiguity(tmp_path) as scene:
        expected = scene.routes[route]
        handle = _published(sync, scene.root)
        routes.run(route, tmp_path)
        before = routes.records_by_name()
        reported = _check(sync, handle, expected.outcome)
        _assert_ownership_agrees()
        # COPY-04, COPY-17: detection, and the refusals, changed no record, manifest, or content.
        assert routes.records_by_name() == before
        runtime.invalidate()
        assert sync.copied_bindings() == reported  # COPY-03: the same once the state is rebuilt
        if expected.index_untouched:
            assert _index_entry() == bpy.data.collections["Shot"]  # COPY-06: the index isn't copied
        save_and_reopen(tmp_path / "copies.blend")
        reopened = _check(sync, handle, expected.reopened or expected.outcome)
        _assert_ownership_agrees()
        if expected.reopened is None:
            assert reopened == reported  # COPY-02, COPY-03: the same after save and reopen
        if expected.index_untouched:
            assert _index_entry() == bpy.data.collections["Shot"]


def test_a_full_copy_scenes_content_is_its_own(sync: Synchronization, tmp_path: Path) -> None:
    # OWN-16 on "full-copy-scene": each copy's content is managed by its own manifest.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = _published(sync, scene.root)
        routes.run("full-copy-scene", tmp_path)
        handle.synchronize(0)
        for name in ("Shot", "Shot.001"):
            [obj] = bpy.data.collections[name].objects
            assert [(c.binding_id, c.destination.name) for c in runtime.claims_on(obj)] == [(handle.binding_id, name)]


def test_a_duplicated_object_is_unmanaged(sync: Synchronization, tmp_path: Path) -> None:
    # OWN-16 on "duplicated-object": Object > Duplicate copies the object, and no manifest names the copy.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = _published(sync, scene.root)
        routes.run("duplicated-object", tmp_path)
        handle.synchronize(0)
        [copy] = (obj for obj in bpy.data.objects if obj.name != "Managed")
        assert runtime.claims_on(copy) == []
        assert len(runtime.claims_on(bpy.data.objects["Managed"])) == 1


def test_a_copy_is_found_at_the_next_synchronization(sync: Synchronization, tmp_path: Path) -> None:
    # COPY-18, F-OWNERSHIP-AMBIGUITY "found-at-synchronization": a collection copied by script adds no scene,
    # so nothing reports it until a synchronization looks; for the canonical candidate, that succeeds.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = _published(sync, scene.root)
        assert sync.copied_bindings() == []  # the state is built
        routes.run("collection-copy", tmp_path)
        assert sync.copied_bindings() == []
        assert handle.synchronize(0).state is ResultState.SUCCESS
        [report] = sync.copied_bindings()
        assert [(c.scene, c.destination, c.canonical) for c in report.candidates] == [
            ("Scene", "Shot", True),
            (None, "Shot.001", False),
        ]


def test_a_write_restores_a_lost_index_entry(sync: Synchronization, tmp_path: Path) -> None:
    # COPY-19, F-OWNERSHIP-AMBIGUITY "restored-entry": with the index's Text removed, detection writes none;
    # the next write to the binding's records does, so a later full copy leaves the original canonical.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = _published(sync, scene.root)
        bpy.data.texts.remove(bpy.data.texts[bindings.INDEX_NAME])
        runtime.invalidate()
        assert handle.synchronize(0).state is ResultState.SUCCESS
        assert sync.bindings(_scene()) == [handle]
        assert bindings.index_texts() == []
        assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE).state is ResultState.SUCCESS
        assert _index_entry() == bpy.data.collections["Shot"]
        routes.run("full-copy-scene", tmp_path)
        _check(sync, handle, copies.INDEXED)


def test_a_cleared_entry_is_kept(sync: Synchronization, tmp_path: Path) -> None:
    # COPY-19: an entry naming no destination isn't restored by a write.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = _published(sync, scene.root)
        routes.run("entry-cleared", tmp_path)
        assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE).state is ResultState.SUCCESS
        assert _index_entry() is None


def test_attaching_skips_a_disabled_binding(sync: Synchronization, tmp_path: Path) -> None:
    # COPY-16: attaching writes the configuration, which a binding with no canonical candidate refuses.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = sync.create_attached_binding(_scene(), "shot", name="Shot")
        routes.run("index-lost", tmp_path)
        assert sync.copied_bindings()[0].disabled
        caller = open_fresh(scene.root)
        assert sync.attach("shot", caller).attached == ()
        assert handle.binding_id not in sync.stages
        assert handle.synchronize(0).state is ResultState.FATAL_FAILURE
