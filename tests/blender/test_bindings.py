"""Bindings in Blender data: their records, save/reopen, undo, and the source key contract.

Through the synchronization API on a fresh process state per test (lifecycle.md#binding-state,
source-access.md#source-identity, source-access.md#canonical-candidate).
"""

from __future__ import annotations

import gc
from dataclasses import replace
from typing import TYPE_CHECKING

import bpy
import pytest
from pxr import Sdf, Usd

from fixtures import records as record_fixtures
from fixtures import source_access
from fixtures.scenes import Scene, copy_scene
from proscenium import addon, binding_state, bindings, indexes, records
from proscenium.binding_state import Generation, LastAttempt
from proscenium.bindings import BindingConfig, BindingIndex, DestinationTag
from proscenium.core.source_access import PayloadPolicy, SourceKind
from proscenium.records import NAMESPACE, Loaded, RecordRefused
from proscenium.synchronization import (
    AttachResult,
    BindingHandle,
    BindingNotFound,
    Category,
    Result,
    ResultState,
    Severity,
    Synchronization,
)
from support import undo
from support.blend import save_and_reopen

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType


def _scene() -> bpy.types.Scene:
    # Looked up each time, by name: a datablock reference doesn't survive undo or a file load.
    return bpy.data.scenes["Scene"]


def _root(tmp_path: Path) -> Path:
    return copy_scene(Scene.SOURCE_ACCESS, tmp_path) / "root.usda"


def _config(handle: BindingHandle) -> BindingConfig:
    """The binding's configuration as its record stores it, read from the scenes, not the bindings' state."""
    [config] = [c for _, binding_id, c in bindings.all_bindings() if binding_id == handle.binding_id]
    assert isinstance(config, Loaded)
    return config.record


def _index() -> BindingIndex:
    [text] = bindings.index_texts()
    result = records.read(text, bindings.INDEX_KEY, bindings.INDEX)
    assert isinstance(result, Loaded)
    return result.record


def _destination_tag(collection: bpy.types.Collection) -> DestinationTag:
    result = records.read(collection, bindings.TAG_KEY, bindings.TAG)
    assert isinstance(result, Loaded)
    return result.record


# Records.


def test_creating_a_binding_writes_records_that_refer_to_each_other(sync: Synchronization, tmp_path: Path) -> None:
    # COPY-07, and the mutual reference the canonical-candidate rule reads; on F-BINDING-STATE.
    with source_access.binding_state(tmp_path) as scene:
        handle = sync.create_file_binding(_scene(), scene.root, name="Shot")
    config = _config(handle)
    destination = bpy.data.collections["Shot"]
    assert config == BindingConfig(SourceKind.FILE, str(scene.root), None, None, destination, PayloadPolicy.LOAD_ALL)
    assert destination.name in _scene().collection.children
    assert _destination_tag(destination) == DestinationTag(handle.binding_id, _scene())
    assert _index() == BindingIndex({handle.binding_id: destination})
    [text] = bindings.index_texts()
    assert text.name == ".proscenium"
    assert text.use_fake_user


def test_the_enums_are_stored_as_their_values(sync: Synchronization, tmp_path: Path) -> None:
    # ID properties hold plain strings, and loading gives the enum members back.
    handle = sync.create_file_binding(_scene(), _root(tmp_path), payload_policy=PayloadPolicy.LOAD_NONE)
    stored = records.stored(_scene(), bindings.config_key(handle.binding_id))
    assert isinstance(stored, dict)
    assert [(stored[f], type(stored[f])) for f in ("source", "payload_policy")] == [("file", str), ("load_none", str)]
    config = _config(handle)
    assert (config.source, config.payload_policy) == (SourceKind.FILE, PayloadPolicy.LOAD_NONE)
    assert type(config.source) is SourceKind
    assert type(config.payload_policy) is PayloadPolicy


def test_a_scenes_bindings(sync: Synchronization, tmp_path: Path) -> None:
    file_backed = sync.create_file_binding(_scene(), _root(tmp_path))
    attached = sync.create_attached_binding(_scene(), "shot")
    other = bpy.data.scenes.new("Other")
    assert sync.bindings(_scene()) == [file_backed, attached]
    assert sync.bindings(other) == []
    assert _index().destinations.keys() == {file_backed.binding_id, attached.binding_id}


def test_records_survive_save_and_reopen(sync: Synchronization, tmp_path: Path) -> None:
    # STATE-01: identity, source information, destination, target scene, and requested settings; on F-BINDING-STATE.
    with source_access.binding_state(tmp_path) as scene:
        root = scene.root
        file_backed = sync.create_file_binding(_scene(), root, payload_policy=PayloadPolicy.LOAD_NONE, name="F")
        attached = sync.create_attached_binding(_scene(), scene.key, name="A")
        sync.attach(scene.key, scene.caller)
        identifier = scene.caller.GetRootLayer().identifier
    save_and_reopen(tmp_path / "bindings.blend")
    f, a = bpy.data.collections["F"], bpy.data.collections["A"]
    assert _config(file_backed) == BindingConfig(SourceKind.FILE, str(root), None, None, f, PayloadPolicy.LOAD_NONE)
    assert _config(attached) == BindingConfig(SourceKind.ATTACHED, None, "shot", identifier, a, PayloadPolicy.LOAD_ALL)
    assert sync.bindings(_scene()) == [file_backed, attached]
    assert _destination_tag(f) == DestinationTag(file_backed.binding_id, _scene())
    assert _destination_tag(a) == DestinationTag(attached.binding_id, _scene())
    assert _index() == BindingIndex({file_backed.binding_id: f, attached.binding_id: a})


def test_a_relative_path_resolves_against_the_blend(sync: Synchronization, tmp_path: Path) -> None:
    _root(tmp_path)
    bpy.ops.wm.save_as_mainfile(filepath=str(tmp_path / "shot.blend"))
    handle = sync.create_file_binding(_scene(), "//root.usda")
    assert _config(handle).path == "//root.usda"
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)


def test_a_relative_path_follows_the_blend_when_saved_elsewhere(sync: Synchronization, tmp_path: Path) -> None:
    _root(tmp_path / "a")
    moved = _root(tmp_path / "b")
    bpy.ops.wm.save_as_mainfile(filepath=str(tmp_path / "a" / "shot.blend"))
    handle = sync.create_file_binding(_scene(), "//root.usda")
    handle.synchronize(0)
    bpy.ops.wm.save_as_mainfile(filepath=str(tmp_path / "b" / "shot.blend"))
    handle.synchronize(0)
    live = handle.live_stage()
    assert live is not None
    assert live.GetRootLayer().realPath == str(moved)


def test_a_relative_path_needs_a_saved_blend(sync: Synchronization) -> None:
    with pytest.raises(ValueError, match="hasn't been saved"):
        sync.create_file_binding(_scene(), "//root.usda")
    assert sync.bindings(_scene()) == []


def test_an_unreadable_index_stops_creation_before_any_change(sync: Synchronization, tmp_path: Path) -> None:
    sync.create_file_binding(_scene(), _root(tmp_path))
    [text] = bindings.index_texts()
    text[NAMESPACE][bindings.INDEX_KEY] = {records.VERSION_KEY: 99}
    collections = len(bpy.data.collections)
    with pytest.raises(RecordRefused):
        sync.create_file_binding(_scene(), _root(tmp_path / "other"))
    assert len(bpy.data.collections) == collections
    assert len(sync.bindings(_scene())) == 1


def test_two_indexes_stop_creation(sync: Synchronization, tmp_path: Path) -> None:
    # Copies the canonical-candidate rule can't decide between; repairing them is not creation's job.
    sync.create_file_binding(_scene(), _root(tmp_path))
    [text] = bindings.index_texts()
    text.copy()  # ID.copy copies the ID properties, the index record with them
    assert len(bindings.index_texts()) == 2
    collections = len(bpy.data.collections)
    with pytest.raises(ValueError, match="2 binding indexes"):
        sync.create_file_binding(_scene(), _root(tmp_path / "other"))
    assert len(bpy.data.collections) == collections
    assert len(sync.bindings(_scene())) == 1


def test_settings_change_only_their_binding(sync: Synchronization, tmp_path: Path) -> None:
    # BIND-10, for the configuration: F-MULTI-BINDING's file and attached bindings on one source.
    with source_access.multi_binding(tmp_path) as scene:
        root = scene.roots[".usda"]
        changed, other = sync.create_file_binding(_scene(), root), sync.create_file_binding(_scene(), root)
        attached = sync.create_attached_binding(_scene(), "shot")
        sync.attach("shot", scene.caller)
        before = [_config(h) for h in (other, attached)]
        changed.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
        assert [_config(h) for h in (other, attached)] == before
        assert _config(changed).payload_policy == "load_none"


# Handles across undo, redo, and save/reopen.


def test_handles_survive_undo_redo_and_reopen(sync: Synchronization, tmp_path: Path) -> None:
    # API-01: a handle holds only the identifier, so nothing it holds goes stale. On F-BINDING-STATE.
    undo.require_global_undo()
    with source_access.binding_state(tmp_path) as scene:
        handle = sync.create_file_binding(_scene(), scene.root)
    undo.push("base")
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    undo.push("change")
    undo.undo()
    assert handle.requested_settings().payload_policy is PayloadPolicy.LOAD_ALL
    undo.redo()
    assert handle.requested_settings().payload_policy is PayloadPolicy.LOAD_NONE
    save_and_reopen(tmp_path / "handles.blend")
    assert BindingHandle(handle.binding_id) == handle
    assert handle.requested_settings().payload_policy is PayloadPolicy.LOAD_NONE
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)


def test_handles_on_f_binding_state(sync: Synchronization, tmp_path: Path) -> None:
    # API-02, API-03, API-07, ICON-32: synchronizing changes no setting and reuses the binding's own source
    # stage as its live stage; set_settings and reload record or reread without synchronizing.
    with source_access.binding_state(tmp_path) as scene:
        handle = sync.create_file_binding(_scene(), scene.root)
        before = _config(handle)
        assert handle.synchronize(Usd.TimeCode.Default()) == Result(ResultState.SUCCESS)
        assert _config(handle) == before  # API-02
        live = handle.live_stage()
        assert live is not None and live != scene.caller
        assert handle.synchronize(3) == Result(ResultState.SUCCESS)
        assert handle.live_stage() == live  # ICON-32: the same stage after a second refresh
        assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE) == Result(ResultState.SUCCESS)
        assert handle.requested_settings().payload_policy is PayloadPolicy.LOAD_NONE  # API-03
        assert live.GetLoadSet()  # not applied: nothing synchronized
        assert binding_state.read_last_attempt(_scene(), handle.binding_id) is None
        assert handle.reload() == Result(ResultState.SUCCESS)
        assert handle.requested_settings().payload_policy is PayloadPolicy.LOAD_NONE  # API-07
        assert handle.live_stage() == live
        assert handle.synchronize(3) == Result(ResultState.SUCCESS)
        assert not live.GetLoadSet()  # applied at the next synchronization


def test_undoing_creation_makes_handles_raise(sync: Synchronization, tmp_path: Path) -> None:
    # API-06: the binding is gone, so every method of its handles raises, as does one made afterwards;
    # redo brings it back. On F-BINDING-STATE.
    undo.require_global_undo()
    undo.push("base")
    with source_access.binding_state(tmp_path) as scene:
        handle = sync.create_file_binding(_scene(), scene.root)
    undo.push("create")
    undo.undo()
    for each in (handle, BindingHandle(handle.binding_id)):
        calls = [
            lambda h=each: h.synchronize(0),
            lambda h=each: h.set_settings(payload_policy=PayloadPolicy.LOAD_NONE),
            each.reload,
            each.requested_settings,
            each.live_stage,
        ]
        for call in calls:
            with pytest.raises(BindingNotFound):
                call()
    undo.redo()
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)


# Reopening.


def test_reopening_synchronizes_nothing(sync: Synchronization, extension: ModuleType, tmp_path: Path) -> None:
    # REOPEN-02, ICON-33: after reopening, no source is open and a file binding has no live stage.
    # A scene with no caller's stage, unlike F-BINDING-STATE's, so its root layer is open only if the binding opened it.
    root = _root(tmp_path)
    handle = sync.create_file_binding(_scene(), root)
    handle.synchronize(0)
    assert handle.live_stage() is not None
    save_and_reopen(tmp_path / "reopen.blend")
    gc.collect()
    assert handle.live_stage() is None
    assert not Sdf.Layer.Find(str(root))
    assert extension.addon.is_registered()


def test_reopening_f_binding_state_synchronizes_nothing(
    sync: Synchronization, extension: ModuleType, tmp_path: Path
) -> None:
    # REOPEN-02, ICON-33 on F-BINDING-STATE: no synchronization runs, so the binding has no source stage,
    # and its published generation and last attempt are as saved. Nothing writes them before M5, so the
    # test does. Its caller's stage keeps the root layer open, so the registry is the evidence.
    with source_access.binding_state(tmp_path) as scene:
        handle = sync.create_file_binding(_scene(), scene.root, name="Shot")
        handle.synchronize(0)
        generation = Generation(handle.binding_id, PayloadPolicy.LOAD_ALL, 0.0, ())
        attempt = LastAttempt(PayloadPolicy.LOAD_ALL, 0.0, ResultState.SUCCESS, ())
        binding_state.write_generation(bpy.data.collections["Shot"], generation)
        binding_state.write_last_attempt(_scene(), handle.binding_id, attempt)
        save_and_reopen(tmp_path / "reopen.blend")
        assert handle.binding_id not in sync.sources
        assert handle.live_stage() is None
        assert binding_state.read_generation(bpy.data.collections["Shot"]) == Loaded(generation, 1)
        assert binding_state.read_last_attempt(_scene(), handle.binding_id) == Loaded(attempt, 1)


def test_an_attached_source_is_unavailable_after_reopening(
    sync: Synchronization, extension: ModuleType, tmp_path: Path
) -> None:
    # SRC-03: until the caller attaches a stage again.
    handle = sync.create_attached_binding(_scene(), "shot")
    with source_access.reattach(tmp_path) as scene:
        sync.attach("shot", scene.caller)
        assert handle.synchronize(0) == Result(ResultState.SUCCESS)
        save_and_reopen(tmp_path / "reopen.blend")
        result = handle.synchronize(0)
        assert result.state is ResultState.FATAL_FAILURE
        assert [d.category for d in result.diagnostics] == [Category.UNAVAILABLE_SOURCE]
        assert sync.attach("shot", scene.caller).attached == (handle.binding_id,)
        assert handle.synchronize(0) == Result(ResultState.SUCCESS)


# A configuration that can't be read.


@pytest.mark.parametrize("name", ["newer", "no-path", "unknown-policy"])
def test_an_unsupported_configuration_is_kept_and_refuses(sync: Synchronization, tmp_path: Path, name: str) -> None:
    # SCHEMA-03: F-SCHEMA-VERSIONS' binding configurations, as another extension version or damage left them.
    with record_fixtures.schema_versions(tmp_path) as versions:
        stored = versions.bindings[name]
        handle = BindingHandle(bindings.new_identifier())
        _scene()[NAMESPACE] = {bindings.config_key(handle.binding_id): stored}
        for result in (
            handle.synchronize(0),
            handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE),
            handle.reload(),
        ):
            assert result.state is ResultState.FATAL_FAILURE
            [diagnostic] = result.diagnostics
            assert (diagnostic.category, diagnostic.severity) == (Category.UNSUPPORTED_RECORD, Severity.ERROR)
            refused = records.load(bindings.CONFIG, stored)
            assert isinstance(refused, records.Refused)
            assert refused.refusal is versions.bindings_refused[name]
            assert diagnostic.message == refused.message
        with pytest.raises(RecordRefused):
            handle.requested_settings()
        assert sync.bindings(_scene()) == [handle]
        assert records.stored(_scene(), bindings.config_key(handle.binding_id)) == stored


# The source key contract (source-access.md#source-identity).


def test_a_key_attaches_every_binding_with_it(sync: Synchronization, tmp_path: Path) -> None:
    # SID-03: two bindings share a key; a third has another.
    a, b = sync.create_attached_binding(_scene(), "shot"), sync.create_attached_binding(_scene(), "shot")
    c = sync.create_attached_binding(_scene(), "other")
    with source_access.reattach(tmp_path) as scene:
        assert sync.attach("shot", scene.caller) == AttachResult(attached=(a.binding_id, b.binding_id), unconfirmed=())
        assert [h.live_stage() for h in (a, b, c)] == [scene.caller, scene.caller, None]


def test_reattachment_needs_an_exact_key(sync: Synchronization, tmp_path: Path) -> None:
    # SID-04: case and whitespace count.
    handle = sync.create_attached_binding(_scene(), "shot")
    with source_access.reattach(tmp_path) as scene:
        for key in ("Shot", " shot", "shot "):
            assert sync.attach(key, scene.caller) == AttachResult(attached=(), unconfirmed=())
        assert handle.live_stage() is None


def test_the_root_layer_never_finds_a_binding(sync: Synchronization, tmp_path: Path) -> None:
    # SID-05: the stored root layer matches, the key doesn't.
    handle = sync.create_attached_binding(_scene(), "shot")
    with source_access.reattach(tmp_path) as scene:
        sync.attach("shot", scene.caller)
        assert sync.attach("other", scene.same_root).attached == ()
        assert handle.live_stage() == scene.caller


def test_a_stage_over_the_same_root_layer_reattaches(sync: Synchronization, tmp_path: Path) -> None:
    handle = sync.create_attached_binding(_scene(), "shot")
    with source_access.reattach(tmp_path) as scene:
        sync.attach("shot", scene.caller)
        assert sync.attach("shot", scene.same_root).attached == (handle.binding_id,)
        assert handle.live_stage() == scene.same_root


def test_a_different_root_layer_needs_confirmation(sync: Synchronization, tmp_path: Path) -> None:
    # SID-06: without confirmation nothing changes for any binding with the key; with it, the stored
    # identifier becomes the new stage's, in the records.
    a, b = sync.create_attached_binding(_scene(), "shot"), sync.create_attached_binding(_scene(), "shot")
    with source_access.reattach(tmp_path) as scene:
        sync.attach("shot", scene.caller)
        c = sync.create_attached_binding(_scene(), "shot")  # unattached, no stored root layer
        refused = sync.attach("shot", scene.other_root)
        assert refused == AttachResult(attached=(), unconfirmed=(a.binding_id, b.binding_id))
        assert [h.live_stage() for h in (a, b, c)] == [scene.caller, scene.caller, None]
        caller = scene.caller.GetRootLayer().identifier
        assert [_config(h).root_layer_identifier for h in (a, b, c)] == [caller, caller, None]
        confirmed = sync.attach("shot", scene.other_root, confirm=True)
        assert confirmed == AttachResult(attached=(a.binding_id, b.binding_id, c.binding_id), unconfirmed=())
        identifier = scene.other_root.GetRootLayer().identifier
        assert [_config(h).root_layer_identifier for h in (a, b, c)] == [identifier] * 3
        assert [h.live_stage() for h in (a, b, c)] == [scene.other_root] * 3


def test_the_stored_identifier_is_the_records_after_undo(sync: Synchronization, tmp_path: Path) -> None:
    # The confirmation rule reads the record, so undoing an attach's record change brings the old identifier back.
    undo.require_global_undo()
    handle = sync.create_attached_binding(_scene(), "shot")
    with source_access.reattach(tmp_path) as scene:
        sync.attach("shot", scene.caller)
        undo.push("base")
        sync.attach("shot", scene.other_root, confirm=True)
        undo.push("replace")
        undo.undo()
        assert _config(handle).root_layer_identifier == scene.caller.GetRootLayer().identifier
        assert sync.attach("shot", scene.same_root).attached == (handle.binding_id,)  # needs no confirmation


def test_attach_never_reaches_a_file_binding(sync: Synchronization, tmp_path: Path) -> None:
    # A file binding on the caller's root layer: only the binding's source kind and key tell them apart.
    with source_access.reattach(tmp_path) as scene:
        handle = sync.create_file_binding(_scene(), scene.root, name="shot")
        assert sync.attach("shot", scene.caller) == AttachResult(attached=(), unconfirmed=())
        handle.synchronize(0)
        assert handle.live_stage() != scene.caller


def _with_key(stored: object, key: str) -> dict[str, object]:
    """A stored attached-source configuration with this key."""
    assert isinstance(stored, dict)
    return stored | {"source": "attached", "path": None, "key": key}


def test_attach_skips_a_configuration_it_cannot_read(sync: Synchronization, tmp_path: Path) -> None:
    with record_fixtures.schema_versions(tmp_path) as versions:
        unreadable = _with_key(versions.bindings["newer"], "shot")
        _scene()[NAMESPACE] = {bindings.config_key(bindings.new_identifier()): unreadable}
        with source_access.reattach(tmp_path / "caller") as scene:
            assert sync.attach("shot", scene.caller) == AttachResult(attached=(), unconfirmed=())


# The records' namespace.


@pytest.mark.parametrize("id_type", addon.RECORD_TYPES, ids=lambda t: t.__name__)
def test_the_namespace_is_registered_so_the_panel_hides_it(extension: ModuleType, id_type: type[bpy.types.ID]) -> None:
    # The Custom Properties panel skips properties the Python API defines (rna_prop_ui.draw).
    runtime = {p.identifier for p in id_type.bl_rna.properties if p.is_runtime}
    assert NAMESPACE in runtime


def test_records_stay_readable_with_the_extension_unregistered(sync: Synchronization, tmp_path: Path) -> None:
    # The records are raw ID properties, readable without the namespace's registered class; the API is not,
    # since its in-memory state needs the extension's handlers.
    handle = sync.create_file_binding(_scene(), _root(tmp_path))
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    expected = _config(handle)
    addon.unregister()
    save_and_reopen(tmp_path / "unregistered.blend")
    assert _config(handle) == replace(expected, destination=bpy.data.collections["root"])
    with pytest.raises(indexes.NotTracking):
        handle.requested_settings()
