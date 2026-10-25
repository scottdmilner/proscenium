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
from proscenium.api.bindings import (
    BindingHandle,
    Bindings,
    DiagnosticCategory,
    ResultState,
)
from proscenium.core.source_access import PayloadPolicy
from proscenium.persistence import binding_records, records
from proscenium.persistence.manifests import Manifest, ManifestEntry
from proscenium.persistence.records import Loaded
from proscenium.runtime import DisabledBindingError
from support import copies as routes
from support import ownership as oracle
from support.blend import save_and_reopen
from support.usd import open_fresh

if TYPE_CHECKING:
    from pathlib import Path

    from fixtures.copies import Outcome
    from proscenium.runtime import CopiedBinding


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _published(bindings: Bindings, root: Path) -> BindingHandle:
    """The binding every route copies: "Shot" on "Scene", its manifest naming "Managed"."""
    handle = bindings.create_file_binding(_scene(), root, name="Shot")
    obj = bpy.data.objects.new("Managed", None)
    bpy.data.collections["Shot"].objects.link(obj)
    runtime.set_manifest(handle.binding_id, Manifest({"a": ManifestEntry(obj, ["/World"], "prim", [])}))
    return handle


def _index_entry() -> bpy.types.Collection | None:
    [text] = binding_records.index_texts()
    index = records.read(text, binding_records.INDEX_KEY, binding_records.INDEX)
    assert isinstance(index, Loaded)
    [destination] = index.record.destinations.values()
    return destination


def _assert_ownership_agrees() -> None:
    # The state's claims are the oracle's for every object: a copy's manifest counts, a record's or a tagged
    # collection's that no record names, so content a copy names is ambiguous (OWN-16).
    expected, _ = oracle.claims()
    for obj in bpy.data.objects:
        assert set(runtime.ownership(obj).claims) == set(expected.get(obj, []))


def _check(bindings: Bindings, handle: BindingHandle, outcome: Outcome) -> list[CopiedBinding]:
    """What the API reports for the binding, against the outcome; returns the report."""
    result = handle.synchronize(0)  # looks for copies first (COPY-18)
    reported = bindings.copied()
    if outcome.reason is copies.DecisionReason.UNIQUE:
        assert reported == []  # COPY-14: nothing to report for a unique identity
        assert result.state is ResultState.SUCCESS
        assert bindings.in_scene(_scene()) == [handle]
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
        found = runtime.find_binding(handle.binding_id)
        assert found is not None and found.scene == _scene()
        for name in scenes:
            assert bindings.in_scene(bpy.data.scenes[name]) == ([handle] if name == "Scene" else [])
    else:
        # COPY-02, COPY-11, COPY-16: every candidate disabled; listed on each scene with one; refused.
        assert not any(c.canonical for c in report.candidates)
        for name in scenes:
            assert bindings.in_scene(bpy.data.scenes[name]) == [handle]
        for refused in (result, handle.reload(), handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)):
            assert refused.state is ResultState.FATAL_FAILURE
            assert [d.category for d in refused.diagnostics] == [DiagnosticCategory.COPIED_BINDING]
            assert all(
                c.destination is None or c.destination in refused.diagnostics[0].message for c in report.candidates
            )
        assert bindings.stages.get(handle.binding_id) is None
        with pytest.raises(DisabledBindingError):
            handle.requested_settings()
        assert handle.live_stage() is None
        # The runtime's lookup finds it disabled, with its copies; its manifest and writes raise.
        binding_id = handle.binding_id
        assert runtime.find_binding(binding_id) == runtime.FoundBinding(binding_id, None, None, None, report)
        for call in (
            lambda: runtime.manifest(binding_id),
            lambda: runtime.set_manifest(binding_id, Manifest({})),
            lambda: runtime.set_manifest_entries(binding_id, {}, ["a"]),
        ):
            with pytest.raises(DisabledBindingError):
                call()
    return reported


@pytest.mark.parametrize("route", list(copies.ROUTES))
def test_route(bindings: Bindings, tmp_path: Path, route: str) -> None:
    with copies.ownership_ambiguity(tmp_path) as scene:
        expected = scene.routes[route]
        handle = _published(bindings, scene.root)
        routes.run(route, tmp_path)
        before = routes.records_by_name()
        reported = _check(bindings, handle, expected.outcome)
        _assert_ownership_agrees()
        # COPY-04, COPY-17: detection, and the refusals, changed no record, manifest, or content.
        assert routes.records_by_name() == before
        runtime.invalidate()
        assert bindings.copied() == reported  # COPY-03: the same once the state is rebuilt
        if expected.index_untouched:
            assert _index_entry() == bpy.data.collections["Shot"]  # COPY-06: the index isn't copied
        save_and_reopen(tmp_path / "copies.blend")
        reopened = _check(bindings, handle, expected.reopened or expected.outcome)
        _assert_ownership_agrees()
        if expected.reopened is None:
            assert reopened == reported  # COPY-02, COPY-03: the same after save and reopen
        if expected.index_untouched:
            assert _index_entry() == bpy.data.collections["Shot"]


def test_a_full_copy_scenes_content_is_its_own(bindings: Bindings, tmp_path: Path) -> None:
    # OWN-16 on "full-copy-scene": each copy's content is managed by its own manifest.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = _published(bindings, scene.root)
        routes.run("full-copy-scene", tmp_path)
        handle.synchronize(0)
        for name in ("Shot", "Shot.001"):
            [obj] = bpy.data.collections[name].objects
            claims = runtime.ownership(obj).claims
            assert [(c.binding_id, c.destination.name) for c in claims] == [(handle.binding_id, name)]


def test_a_duplicated_object_is_unmanaged(bindings: Bindings, tmp_path: Path) -> None:
    # OWN-16 on "duplicated-object": Object > Duplicate copies the object, and no manifest names the copy.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = _published(bindings, scene.root)
        routes.run("duplicated-object", tmp_path)
        handle.synchronize(0)
        [copy] = (obj for obj in bpy.data.objects if obj.name != "Managed")
        assert runtime.ownership(copy).claims == ()
        assert len(runtime.ownership(bpy.data.objects["Managed"]).claims) == 1


def test_a_copy_is_found_at_the_next_synchronization(bindings: Bindings, tmp_path: Path) -> None:
    # COPY-18, F-OWNERSHIP-AMBIGUITY "found-at-synchronization": a collection copied by script adds no scene,
    # so nothing reports it until a synchronization looks; for the canonical candidate, that succeeds.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = _published(bindings, scene.root)
        assert bindings.copied() == []  # the state is built
        routes.run("collection-copy", tmp_path)
        assert bindings.copied() == []
        assert handle.synchronize(0).state is ResultState.SUCCESS
        [report] = bindings.copied()
        assert [(c.scene, c.destination, c.canonical) for c in report.candidates] == [
            ("Scene", "Shot", True),
            (None, "Shot.001", False),
        ]


def test_a_write_restores_a_lost_index_entry(bindings: Bindings, tmp_path: Path) -> None:
    # COPY-19, F-OWNERSHIP-AMBIGUITY "restored-entry": with the index's Text removed, detection writes none;
    # the next write to the binding's records does, so a later full copy leaves the original canonical.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = _published(bindings, scene.root)
        bpy.data.texts.remove(bpy.data.texts[binding_records.INDEX_NAME])
        runtime.invalidate()
        assert handle.synchronize(0).state is ResultState.SUCCESS
        assert bindings.in_scene(_scene()) == [handle]
        assert binding_records.index_texts() == []
        assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE).state is ResultState.SUCCESS
        assert _index_entry() == bpy.data.collections["Shot"]
        routes.run("full-copy-scene", tmp_path)
        _check(bindings, handle, copies.INDEXED)


def test_a_cleared_entry_is_kept(bindings: Bindings, tmp_path: Path) -> None:
    # COPY-19: an entry naming no destination isn't restored by a write.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = _published(bindings, scene.root)
        routes.run("entry-cleared", tmp_path)
        assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE).state is ResultState.SUCCESS
        assert _index_entry() is None


def test_attaching_skips_a_disabled_binding(bindings: Bindings, tmp_path: Path) -> None:
    # COPY-16: attaching writes the configuration, which a binding with no canonical candidate refuses.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = bindings.create_attached_binding(_scene(), "shot", name="Shot")
        routes.run("index-lost", tmp_path)
        assert bindings.copied()[0].disabled
        caller = open_fresh(scene.root)
        assert bindings.attach("shot", caller).attached == ()
        assert bindings.stages.get(handle.binding_id) is None
        assert handle.synchronize(0).state is ResultState.FATAL_FAILURE
