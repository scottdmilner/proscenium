"""Reopening a .blend with its bindings' sources unavailable (lifecycle.md#reopening), on F-OFFLINE.

Nothing publishes until M5, so each test builds the saved display the fixture describes and records it
as a publication would, in the manifest and the generation, then saves, makes the source unavailable,
and reopens. Each checks after reopening and again after a synchronization, which fails.
"""

from __future__ import annotations

import gc
from dataclasses import replace
from typing import TYPE_CHECKING

import bpy
from pxr import Sdf

from fixtures import source_access
from proscenium import binding_state, indexes
from proscenium.records import Refused
from proscenium.synchronization import BindingHandle, Category, ResultState, Synchronization
from support.blend import collection_content, save_and_reopen
from support.display import expected_content, publish_by_hand

if TYPE_CHECKING:
    from pathlib import Path

    from fixtures.source_access import SavedDisplay


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _destination(handle: BindingHandle) -> bpy.types.Collection:
    config = indexes.config(handle.binding_id)
    assert config is not None and not isinstance(config, Refused) and config.destination is not None
    return config.destination


def _saved(handle: BindingHandle) -> dict[str, object]:
    """The binding's records and its destination's content, by name: references don't survive a reopen."""
    config = indexes.config(handle.binding_id)
    assert config is not None and not isinstance(config, Refused)
    destination = _destination(handle)
    manifest = indexes.manifest(handle.binding_id)
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
