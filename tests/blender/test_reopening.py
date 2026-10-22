"""Reopening a .blend whose bindings' sources are unavailable, or whose destination was removed (lifecycle.md).

F-OFFLINE (lifecycle.md#reopening): nothing publishes until M5, so each test builds the saved display the
fixture describes and records it as a publication would, in the manifest and the generation, then saves,
makes the source unavailable, and reopens. Each checks after reopening and again after a synchronization,
which fails. F-BINDING-STATE's removed destination (lifecycle.md#removed-destination) goes through the same.
"""

from __future__ import annotations

import gc
from dataclasses import replace
from typing import TYPE_CHECKING

import bpy
from pxr import Sdf

from fixtures import source_access
from proscenium import runtime
from proscenium.api.synchronization import BindingHandle, Category, RequestedSettings, ResultState, Synchronization
from proscenium.core.source_access import PayloadPolicy
from proscenium.persistence import binding_state, bindings, records
from proscenium.persistence.binding_state import LastAttempt
from proscenium.persistence.manifests import Manifest, ManifestEntry
from proscenium.persistence.records import Loaded, Refused
from support.blend import collection_content, save_and_reopen
from support.display import expected_content, publish_by_hand

if TYPE_CHECKING:
    from pathlib import Path

    from fixtures.source_access import SavedDisplay
    from proscenium.persistence.bindings import BindingConfig


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _destination(handle: BindingHandle) -> bpy.types.Collection:
    config = runtime.config(handle.binding_id)
    assert config is not None and not isinstance(config, Refused) and config.destination is not None
    return config.destination


def _saved(handle: BindingHandle) -> dict[str, object]:
    """The binding's records and its destination's content, by name: references don't survive a reopen."""
    config = runtime.config(handle.binding_id)
    assert config is not None and not isinstance(config, Refused)
    destination = _destination(handle)
    manifest = runtime.manifest(handle.binding_id)
    assert manifest is not None and not isinstance(manifest, Refused)
    entries = {
        key: (entry.datablock and entry.datablock.name, entry.covers, entry.role, entry.uses)
        for key, entry in manifest.record.entries.items()
    }
    generation = binding_state.read_generation(destination)
    assert generation is not None and not isinstance(generation, Refused)
    return {
        "config": replace(config, destination=None),
        "destination": destination.name,
        "entries": entries,
        "generation": generation.record,
        "content": collection_content(destination),
    }


def _publish(handle: BindingHandle, display: SavedDisplay) -> dict[str, object]:
    """Publish display by hand, and what is saved: built as the fixture describes, so later checks compare to it."""
    publish_by_hand(handle.binding_id, _destination(handle), display)
    saved = _saved(handle)
    assert saved["content"] == expected_content(display)
    names = {"world": "World", "ref": "Ref", "ref-mesh": "Ref", "ref-material": "Ref"}
    assert saved["entries"] == {key: (names[key], *entry) for key, entry in display.entries.items()}
    return saved


def _check_kept(sync: Synchronization, handle: BindingHandle, saved: dict[str, object], category: Category) -> None:
    # REOPEN-04, REOPEN-05, REOPEN-07: the binding is listed with its records, and the display unchanged,
    # after reopening and after a synchronization that fails for the unavailable source.
    assert sync.bindings(_scene()) == [handle]
    assert _saved(handle) == saved
    result = handle.synchronize(0)
    assert result.state is ResultState.FATAL_FAILURE
    assert [d.category for d in result.diagnostics] == [category]
    assert sync.bindings(_scene()) == [handle]
    assert _saved(handle) == saved


def test_moved_file_source(sync: Synchronization, tmp_path: Path) -> None:
    # F-OFFLINE "moved-file": the binding synchronized before saving, so the source was open; reopening drops it.
    with source_access.offline(tmp_path) as scene:
        handle = sync.create_file_binding(_scene(), scene.root, name="Shot")
        saved = _publish(handle, scene.display)
        assert handle.synchronize(0).state is ResultState.SUCCESS
        scene.move_away()
        save_and_reopen(tmp_path / "offline.blend")
        gc.collect()
        assert not Sdf.Layer.Find(str(scene.root))
        assert not scene.root.exists()
        _check_kept(sync, handle, saved, Category.UNAVAILABLE_SOURCE)


def test_unattached_source(sync: Synchronization, tmp_path: Path) -> None:
    # F-OFFLINE "unattached": the caller's stage was attached when saving, and still exists, but reopening
    # leaves nothing attached under the key.
    with source_access.offline(tmp_path) as scene:
        caller = scene.open_caller()
        handle = sync.create_attached_binding(_scene(), scene.key, name="Shot")
        sync.attach(scene.key, caller)
        saved = _publish(handle, scene.display)
        assert handle.synchronize(0).state is ResultState.SUCCESS
        save_and_reopen(tmp_path / "offline.blend")
        _check_kept(sync, handle, saved, Category.UNAVAILABLE_SOURCE)


# A removed destination.


def _index_entry(binding_id: str) -> tuple[bool, bpy.types.Collection | None]:
    [text] = bindings.index_texts()
    index = records.read(text, bindings.INDEX_KEY, bindings.INDEX)
    assert isinstance(index, Loaded)
    return binding_id in index.record.destinations, index.record.destinations.get(binding_id)


def _check_removed(sync: Synchronization, handle: BindingHandle, saved: BindingConfig, attempt: LastAttempt) -> None:
    # DEST-01: listed, with its configuration, last attempt, and index entry, its destination pointer cleared.
    assert sync.bindings(_scene()) == [handle]
    config = runtime.config(handle.binding_id)
    assert config is not None and not isinstance(config, Refused)
    assert config == saved
    assert binding_state.read_last_attempt(_scene(), handle.binding_id) == Loaded(attempt, 1)
    assert _index_entry(handle.binding_id) == (True, None)
    # DEST-04: no manifest, no resources, and the object it displayed claims no owner.
    assert runtime.manifest(handle.binding_id) is None
    assert runtime.resource(handle.binding_id, "a") is None
    assert runtime.claims_on(bpy.data.objects["Managed"]) == []
    # DEST-02: a fatal failure, with no source made for it and no destination created.
    collections = set(bpy.data.collections.keys())
    result = handle.synchronize(0)
    assert result.state is ResultState.FATAL_FAILURE
    assert [d.category for d in result.diagnostics] == [Category.REMOVED_DESTINATION]
    assert handle.binding_id in result.diagnostics[0].message
    assert handle.binding_id not in sync.sources
    assert set(bpy.data.collections.keys()) == collections


def test_removed_destination(sync: Synchronization, tmp_path: Path) -> None:
    # F-BINDING-STATE "removed-destination": the destination held a managed object that something else
    # also uses, so the object outlives it. Checked once it's removed, and again after save and reopen.
    with source_access.binding_state(tmp_path) as scene:
        handle = sync.create_file_binding(_scene(), scene.root, name="Shot")
        obj = bpy.data.objects.new("Managed", None)
        bpy.data.collections["Shot"].objects.link(obj)
        _scene().collection.objects.link(obj)
        runtime.set_manifest(handle.binding_id, Manifest({"a": ManifestEntry(obj, ["/World"], "prim", [])}))
        attempt = LastAttempt(PayloadPolicy.LOAD_ALL, 0.0, ResultState.SUCCESS, ())
        binding_state.write_last_attempt(_scene(), handle.binding_id, attempt)
        assert runtime.claims_on(obj) != []
        before = runtime.config(handle.binding_id)
        assert before is not None and not isinstance(before, Refused)
        bpy.data.collections.remove(bpy.data.collections["Shot"])
        config = replace(before, destination=None)
        _check_removed(sync, handle, config, attempt)
        save_and_reopen(tmp_path / "removed.blend")
        _check_removed(sync, handle, config, attempt)
        # DEST-03: its requested settings read as saved, and a change is written to its configuration.
        assert handle.requested_settings() == RequestedSettings(PayloadPolicy.LOAD_ALL)
        assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE).state is ResultState.SUCCESS
        [(_, binding_id, stored)] = bindings.all_bindings()
        assert binding_id == handle.binding_id and isinstance(stored, Loaded)
        assert stored.record == replace(config, payload_policy=PayloadPolicy.LOAD_NONE)
