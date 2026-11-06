"""Copied-binding detection on F-OWNERSHIP-AMBIGUITY (source-access.md#copied-bindings, #canonical-candidate).

Each route runs on a published binding, and the test checks what the synchronization API reports against
the outcome the fixture derives from the canonical-candidate rule: after a synchronization, which looks
for copies first, again after the bindings' state is rebuilt, and again after save and reopen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest

from fixtures import copies, transaction
from proscenium.binding import runtime
from proscenium.binding.persistence import binding_state, configs, manifests, records
from proscenium.binding.persistence.manifests import Manifest
from proscenium.binding.persistence.records import Loaded
from proscenium.binding.results import DiagnosticCode, ResultState
from proscenium.binding.runtime import ownership_index
from proscenium.binding.runtime.binding_configs import DisabledBindingError
from proscenium.binding.source_access.stages import PayloadPolicy
from support import copies as routes
from support import ownership as oracle
from support.blend import save_and_reopen
from support.manifests import key
from support.usd import binding_on_file, open_fresh

if TYPE_CHECKING:
    from pathlib import Path

    from pxr import Usd

    from fixtures.copies import Outcome
    from proscenium.api.bindings import BindingHandle, Bindings
    from proscenium.binding.runtime.copy_detection import CopiedBinding
    from proscenium.binding.source_access.identifiers import BindingId


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _published(bindings: Bindings, root: Path) -> BindingHandle:
    """The binding every route copies: "Shot" on "Scene", holding what its synchronization published."""
    handle = binding_on_file(bindings, _scene(), root, name="Shot")
    assert handle.synchronize(0).state is ResultState.SUCCESS
    assert len(bpy.data.collections["Shot"].objects) == len(transaction.DRAWN[PayloadPolicy.LOAD_ALL])
    return handle


def _republished(found: dict[tuple[str, str], Any], binding_id: BindingId) -> dict[tuple[str, str], Any]:
    """Found without what the original's synchronization writes when it publishes again.

    Its destination's manifest, generation, and objects, its last attempt, and the objects it makes, which have no
    records. A restored index entry, where the route lost the index, is a write's (COPY-19).
    """
    kept = {}
    for (kind, name), value in found.items():
        if (kind == "object" and not value) or (kind, name) == ("objects in", "Shot"):
            continue
        dropped = {
            ("collection", "Shot"): {manifests.MANIFEST_KEY, binding_state.GENERATION_KEY},
            ("scene", "Scene"): {binding_state.ATTEMPT_PREFIX + binding_id},
        }.get((kind, name), set())
        kept[kind, name] = {k: v for k, v in value.items() if k not in dropped} if dropped else value
    return kept


def _index_entry() -> bpy.types.Collection | None:
    [text] = configs.index_texts()
    index = records.read(text, configs.INDEX_KEY, configs.INDEX)
    assert isinstance(index, Loaded)
    [destination] = index.record.destinations.values()
    return destination


def _evaluation(bindings: Bindings, handle: BindingHandle) -> Usd.Stage | None:
    stages = bindings.stages.get(handle.binding_id)
    return None if stages is None else stages.evaluation_stage


def _check(bindings: Bindings, handle: BindingHandle, outcome: Outcome) -> list[CopiedBinding]:
    """What the API reports for the binding, against the outcome; returns the report."""
    evaluation = _evaluation(bindings, handle)
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
        found = runtime.binding_configs.find_binding(handle.binding_id)
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
            assert [d.code for d in refused.diagnostics] == [DiagnosticCode.COPIED_BINDING]
            assert all(
                c.destination is None or c.destination in refused.diagnostics[0].message for c in report.candidates
            )
        assert _evaluation(bindings, handle) is evaluation  # the refusals acquired nothing
        assert handle.live_stage() is None
        with pytest.raises(DisabledBindingError):
            handle.requested_settings()
        assert handle.live_stage() is None
        # The runtime's lookup finds it disabled, with its copies; its manifest and writes raise.
        binding_id = handle.binding_id
        assert runtime.binding_configs.find_binding(binding_id) == runtime.binding_configs.FoundBinding(
            binding_id, None, None, None, report
        )
        for call in (
            lambda: ownership_index.manifest(binding_id),
            lambda: ownership_index.set_manifest(binding_id, Manifest({})),
            lambda: ownership_index.set_manifest_entries(binding_id, {}, [key("a")]),
        ):
            with pytest.raises(DisabledBindingError):
                call()
    return reported


@pytest.mark.parametrize("route", list(copies.ROUTES))
def test_route(bindings: Bindings, tmp_path: Path, route: str) -> None:
    with copies.ownership_ambiguity(tmp_path) as scene:
        expected = scene.routes[route]
        handle = _published(bindings, scene.root)
        found = runtime.binding_configs.find_binding(handle.binding_id)
        assert found is not None
        routes.run(route, tmp_path)
        before = routes.records_by_name()
        synchronized = expected.synchronized or expected.outcome
        reported = _check(bindings, handle, synchronized)
        oracle.assert_agrees()
        # COPY-04, COPY-17: detection, and the refusals, changed no record, manifest, or content; a canonical
        # original's synchronization publishes again, which changes only its own.
        after = routes.records_by_name()
        if expected.outcome.canonical:
            if ("text", configs.INDEX_NAME) not in before:
                del after["text", configs.INDEX_NAME]
            before, after = _republished(before, handle.binding_id), _republished(after, handle.binding_id)
        assert after == before
        runtime.state.invalidate()
        assert bindings.copied() == reported  # COPY-03: the same once the state is rebuilt
        if expected.index_untouched:
            assert _index_entry() == bpy.data.collections["Shot"]  # COPY-06: the index isn't copied
        save_and_reopen(tmp_path / "copies.blend")
        handle.attach(open_fresh(scene.root))
        reopened = _check(bindings, handle, expected.reopened or synchronized)
        oracle.assert_agrees()
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
            objects = bpy.data.collections[name].objects
            assert len(objects) == len(transaction.DRAWN[PayloadPolicy.LOAD_ALL])
            for obj in objects:
                claims = ownership_index.ownership(obj).claims
                assert [(c.binding_id, c.destination.name) for c in claims] == [(handle.binding_id, name)]


def test_a_duplicated_object_is_unmanaged(bindings: Bindings, tmp_path: Path) -> None:
    # OWN-16 on "duplicated-object": Object > Duplicate copies the object, and no manifest names the copy.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = _published(bindings, scene.root)
        published = set(bpy.data.objects)
        routes.run("duplicated-object", tmp_path)
        [copy] = set(bpy.data.objects) - published
        assert ownership_index.ownership(copy).claims == ()
        assert len(ownership_index.ownership(bpy.data.objects[routes.MANAGED]).claims) == 1
        # Synchronizing again publishes new content, and still claims no copy.
        assert handle.synchronize(0).state is ResultState.SUCCESS
        assert ownership_index.ownership(copy).claims == ()
        published = [o for o in bpy.data.collections["Shot"].objects if o != copy]  # the copy stays linked there
        assert all(len(ownership_index.ownership(o).claims) == 1 for o in published)


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
    # the next write to the binding's records does, so a later full copy leaves the original canonical. A
    # synchronization and a settings change are each such a write.
    with copies.ownership_ambiguity(tmp_path) as scene:
        handle = _published(bindings, scene.root)
        for write in (
            lambda: handle.synchronize(0),
            lambda: handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE),
        ):
            bpy.data.texts.remove(bpy.data.texts[configs.INDEX_NAME])
            runtime.state.invalidate()
            assert bindings.in_scene(_scene()) == [handle]
            assert configs.index_texts() == []
            assert write().state is ResultState.SUCCESS
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
        handle = bindings.create_binding(_scene(), name="Shot")
        routes.run("index-lost", tmp_path)
        assert bindings.copied()[0].disabled
        caller = open_fresh(scene.root)
        assert handle.attach(caller).state is ResultState.FATAL_FAILURE
        assert bindings.stages.get(handle.binding_id) is None
        assert handle.synchronize(0).state is ResultState.FATAL_FAILURE
