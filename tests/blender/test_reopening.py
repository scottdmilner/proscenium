"""Reopening a .blend whose bindings' sources are unavailable, or whose destination or target scene was removed.

F-OFFLINE (lifecycle.md#reopening): each test builds the saved display the fixture describes and records it as a
publication would, in the manifest and the generation, then saves, makes the source unavailable, and reopens. Each
checks after reopening and again after a synchronization, which fails. F-BINDING-STATE's removed destination and
removed target scene (lifecycle.md#removed-destination) are checked once removed, and again after save and reopen.
"""

from __future__ import annotations

import gc
from dataclasses import replace
from typing import TYPE_CHECKING

import bpy
import pytest
from pxr import Sdf, Usd

from fixtures import source_access
from proscenium.api.bindings import BindingHandle, BindingNotFoundError, Bindings, Result
from proscenium.binding import runtime
from proscenium.binding.persistence import binding_records, binding_state, id_property_records
from proscenium.binding.persistence.binding_state import LastSynchronizationAttempt
from proscenium.binding.persistence.id_property_records import LoadedRecord
from proscenium.binding.persistence.manifests import Manifest
from proscenium.binding.results import DiagnosticCode, ResultState
from proscenium.binding.runtime import ownership
from proscenium.binding.source_access.binding_settings import new_settings
from proscenium.binding.source_access.stages import PayloadPolicy
from support import undo
from support.blend import collection_content, save_and_reopen
from support.destinations import destination
from support.manifests import key, object_entry
from support.offline_display import expected_content, publish_by_hand
from support.usd import binding_on_file

if TYPE_CHECKING:
    from pathlib import Path

    from fixtures.source_access import SavedDisplay
    from proscenium.binding.persistence.binding_records import BindingConfig
    from proscenium.binding.source_access.binding_ids import BindingId


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _config(handle: BindingHandle) -> BindingConfig:
    found = runtime.binding_operations.find_binding(handle.binding_id)
    assert found is not None and found.config is not None
    return found.config


def _saved(handle: BindingHandle) -> dict[str, object]:
    """The binding's records and its destination's content, by name: references don't survive a reopen."""
    config = _config(handle)
    found = destination(handle)
    manifest = ownership.manifest(handle.binding_id)
    assert isinstance(manifest, LoadedRecord)
    entries = {
        entry_key: (
            entry.datablock and entry.datablock.name,
            entry.source_entity_paths,
            entry.role,
            entry.dependency_entry_keys,
            entry.object_index_in_copy,
        )
        for entry_key, entry in manifest.record.entries.items()
    }
    generation = binding_state.read_generation(found)
    assert isinstance(generation, LoadedRecord)
    assert config.scene is not None
    return {
        "config": replace(config, scene=None),  # a reference doesn't survive a reopen; its name does
        "scene": config.scene.name,
        "destination": found.name,
        "entries": entries,
        "generation": generation.record,
        "content": collection_content(found),
    }


def _publish(handle: BindingHandle, display: SavedDisplay) -> dict[str, object]:
    """Publish display by hand, and what is saved: built as the fixture describes, so later checks compare to it."""
    publish_by_hand(handle.binding_id, destination(handle), display)
    saved = _saved(handle)
    assert saved["content"] == expected_content(display)
    names = {"world": "World", "ref": "Ref", "ref-mesh": "Ref", "ref-material": "Ref"}
    assert saved["entries"] == {
        key(name): (names[name], covers, role, tuple(key(u) for u in uses), place)
        for name, (covers, role, uses, place) in display.entries.items()
    }
    return saved


def _check_kept(bindings: Bindings, handle: BindingHandle, saved: dict[str, object], code: DiagnosticCode) -> None:
    # REOPEN-04, REOPEN-05, REOPEN-07: the binding is listed with its records, and the display unchanged,
    # after reopening and after a synchronization that fails for the unavailable source.
    assert bindings.in_scene(_scene()) == [handle]
    assert _saved(handle) == saved
    result = handle.synchronize(0)
    assert result.state is ResultState.FATAL_FAILURE
    assert [d.code for d in result.diagnostics] == [code]
    assert bindings.in_scene(_scene()) == [handle]
    assert _saved(handle) == saved


def test_reopening_after_source_files_move(bindings: Bindings, tmp_path: Path) -> None:
    # F-OFFLINE "moved-file": the binding's source was open before saving, and reopening drops it. A reload opens it
    # without publishing over the display published by hand.
    with source_access.offline(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root_layer_path, name="Shot")
        saved = _publish(handle, scene.display)
        assert handle.reload().state is ResultState.SUCCESS
        scene.move_away()
        save_and_reopen(tmp_path / "offline.blend")
        gc.collect()
        assert not Sdf.Layer.Find(str(scene.root_layer_path))
        assert not scene.root_layer_path.exists()
        _check_kept(bindings, handle, saved, DiagnosticCode.NO_ATTACHED_STAGE)


def test_unattached_source(bindings: Bindings, tmp_path: Path) -> None:
    # F-OFFLINE "unattached": the caller's stage was attached when saving, and still exists, but reopening
    # leaves the binding unattached.
    with source_access.offline(tmp_path) as scene:
        caller = scene.open_caller()
        handle = bindings.create_binding(_scene(), name="Shot")
        handle.attach(caller)
        saved = _publish(handle, scene.display)
        assert handle.reload().state is ResultState.SUCCESS
        save_and_reopen(tmp_path / "offline.blend")
        _check_kept(bindings, handle, saved, DiagnosticCode.NO_ATTACHED_STAGE)
        assert handle.live_stage() is None
        assert handle.attach(caller) == Result()
        assert handle.live_stage() == caller
        assert _saved(handle) == saved  # attachment alone does not publish or modify the saved display
        assert handle.synchronize(0).state is ResultState.SUCCESS


# A removed destination or target scene.


def _index_entry(binding_id: BindingId) -> tuple[bool, bpy.types.Collection | None]:
    [text] = binding_records.index_texts()
    index = id_property_records.read(text, binding_records.INDEX_KEY, binding_records.INDEX)
    assert isinstance(index, LoadedRecord)
    return binding_id in index.record.destinations, index.record.destinations.get(binding_id)


def _check_gone(bindings: Bindings, handle: BindingHandle, *, release: bool = True) -> None:
    """DEST-05: every method of the binding's handle but release raises, and nothing lists or reports it.

    With release, release is called too, and succeeds.
    """
    calls = (
        lambda: handle.attach(Usd.Stage.CreateInMemory()),
        lambda: handle.synchronize(0),
        lambda: handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE),
        handle.reload,
        handle.retry_cleanup,
        handle.possibly_out_of_date,
        handle.requested_settings,
        handle.live_stage,
    )
    for call in calls:
        with pytest.raises(BindingNotFoundError):
            call()
    if release:
        assert handle.release() is None
    assert all(bindings.in_scene(scene) == [] for scene in bpy.data.scenes)
    assert bindings.copied() == []


def _managed(bindings: Bindings, tmp_path: Path, scene: bpy.types.Scene) -> BindingHandle:
    """A binding "Shot" on scene, displaying an object "Managed" that the scene "Scene" also links."""
    with source_access.binding_state(tmp_path) as source:
        handle = binding_on_file(bindings, scene, source.root_layer_path, name="Shot")
    obj = bpy.data.objects.new("Managed", None)
    bpy.data.collections["Shot"].objects.link(obj)
    _scene().collection.objects.link(obj)
    ownership.set_manifest(handle.binding_id, Manifest({key("a"): object_entry(obj, "/World")}))
    binding_state.write_last_attempt(
        destination(handle), LastSynchronizationAttempt(new_settings(PayloadPolicy.LOAD_ALL), 0.0, ())
    )
    assert ownership.of(obj).claims != ()
    return handle


def test_removed_destination(bindings: Bindings, tmp_path: Path) -> None:
    # F-BINDING-STATE "removed-destination": the binding goes with its destination, and the object it displayed,
    # which the scene also links, outlives it unmanaged (DEST-07); the index entry stays, naming no collection
    # (DEST-09). Checked once removed, and again after save and reopen.
    handle = _managed(bindings, tmp_path, _scene())
    bpy.data.collections.remove(bpy.data.collections["Shot"])
    for check in range(2):
        if check:
            save_and_reopen(tmp_path / "removed.blend")
        _check_gone(bindings, handle)
        assert ownership.of(bpy.data.objects["Managed"]).claims == ()
        assert _index_entry(handle.binding_id) == (True, None)


def test_removed_target_scene(bindings: Bindings, tmp_path: Path) -> None:
    # F-BINDING-STATE "removed-target-scene": the binding goes with its target scene (DEST-05), and its destination,
    # also linked in "Scene", outlives it, keeping its records, whose manifest still claims what it names (DEST-08).
    other = bpy.data.scenes.new("Other")
    handle = _managed(bindings, tmp_path, other)
    _scene().collection.children.link(bpy.data.collections["Shot"])
    stored = id_property_records.stored(bpy.data.collections["Shot"], binding_records.config_key(handle.binding_id))
    assert isinstance(stored, dict)
    bpy.data.scenes.remove(other)
    for check in range(2):
        if check:
            save_and_reopen(tmp_path / "removed.blend")
        _check_gone(bindings, handle)
        shot = bpy.data.collections["Shot"]
        assert id_property_records.stored(shot, binding_records.config_key(handle.binding_id)) == {
            **stored,
            "scene": None,
        }
        claims = ownership.of(bpy.data.objects["Managed"]).claims
        assert [(c.binding_id, c.destination) for c in claims] == [(handle.binding_id, shot)]


def test_undoing_the_removal_restores_the_binding(bindings: Bindings, tmp_path: Path) -> None:
    # DEST-06 on F-BINDING-STATE "removed-destination": undo brings the binding back with its records.
    undo.require_global_undo()
    with source_access.binding_state(tmp_path) as source:
        handle = binding_on_file(bindings, _scene(), source.root_layer_path, name="Shot")
        assert handle.synchronize(0).state is ResultState.SUCCESS
        saved = {
            "config": replace(_config(handle), scene=None),
            "attempt": binding_state.read_last_attempt(destination(handle)),
            "generation": binding_state.read_generation(destination(handle)),
            "entries": sorted(ownership.manifest(handle.binding_id).record.entries),  # ty: ignore[unresolved-attribute]
        }
        undo.push("base")
        bpy.data.collections.remove(bpy.data.collections["Shot"])
        undo.push("removed")
        _check_gone(bindings, handle, release=False)  # its attachment stays for undo (UNDO-06)
        undo.undo()
        assert {
            "config": replace(_config(handle), scene=None),
            "attempt": binding_state.read_last_attempt(destination(handle)),
            "generation": binding_state.read_generation(destination(handle)),
            "entries": sorted(ownership.manifest(handle.binding_id).record.entries),  # ty: ignore[unresolved-attribute]
        } == saved
        assert _config(handle).scene == _scene()
        assert handle.synchronize(0).state is ResultState.SUCCESS
