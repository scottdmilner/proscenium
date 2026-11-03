"""Bindings in Blender data: their records, save/reopen, undo, and the source key contract.

Through the synchronization API on a fresh process state per test (lifecycle.md#binding-state,
source-access.md#source-identity, source-access.md#canonical-candidate).
"""

from __future__ import annotations

import gc
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import bpy
import pytest
from pxr import Sdf, Usd

from fixtures import records as record_fixtures
from fixtures import source_access
from fixtures.scenes import Scene, copy_scene
from proscenium import addon, runtime
from proscenium.api.bindings import (
    AttachResult,
    BindingHandle,
    BindingNotFoundError,
    Bindings,
    DiagnosticCategory,
    RequestedSettings,
    Result,
    ResultState,
    Severity,
)
from proscenium.core.source_access import PayloadPolicy
from proscenium.persistence import binding_records, binding_state, records
from proscenium.persistence.binding_records import BindingConfig, BindingIndex, DestinationTag
from proscenium.persistence.binding_state import Generation, LastAttempt
from proscenium.persistence.records import NAMESPACE, Loaded, RefusedRecordError
from support import undo
from support.blend import save_and_reopen
from support.usd import binding_on_file, open_fresh

if TYPE_CHECKING:
    from types import ModuleType


def _scene() -> bpy.types.Scene:
    # Looked up each time, by name: a datablock reference doesn't survive undo or a file load.
    return bpy.data.scenes["Scene"]


def _root(tmp_path: Path) -> Path:
    return copy_scene(Scene.SOURCE_ACCESS, tmp_path) / "root.usda"


def _config(handle: BindingHandle) -> BindingConfig:
    """The binding's configuration as its record stores it, read from the scenes, not the bindings' state."""
    [config] = [c for _, binding_id, c in binding_records.read_configs() if binding_id == handle.binding_id]
    assert isinstance(config, Loaded)
    return config.record


def _index() -> BindingIndex:
    [text] = binding_records.index_texts()
    result = records.read(text, binding_records.INDEX_KEY, binding_records.INDEX)
    assert isinstance(result, Loaded)
    return result.record


def _destination_tag(collection: bpy.types.Collection) -> DestinationTag:
    result = records.read(collection, binding_records.TAG_KEY, binding_records.TAG)
    assert isinstance(result, Loaded)
    return result.record


# Records.


def test_creating_a_binding_writes_records_that_refer_to_each_other(bindings: Bindings) -> None:
    # COPY-07, API-10, SRC-09: creation stores a key and creates no runtime stage.
    handle = bindings.create_binding(_scene(), "shot", name="Shot")
    destination = bpy.data.collections["Shot"]
    assert _config(handle) == BindingConfig("shot", RequestedSettings(PayloadPolicy.LOAD_ALL), destination=destination)
    assert handle.live_stage() is None
    assert bindings.stages.get(handle.binding_id) is None
    assert destination.name in _scene().collection.children
    assert _destination_tag(destination) == DestinationTag(handle.binding_id, _scene())
    assert _index() == BindingIndex({handle.binding_id: destination})
    [text] = binding_records.index_texts()
    assert text.name.startswith(".")
    assert text.use_fake_user


def test_the_payload_policy_is_stored_as_its_value(bindings: Bindings) -> None:
    handle = bindings.create_binding(_scene(), "shot", payload_policy=PayloadPolicy.LOAD_NONE)
    stored = records.stored(_scene(), binding_records.config_key(handle.binding_id))
    assert stored == {
        records.VERSION_KEY: 1,
        "source_key": "shot",
        "root_layer_identifier": None,
        "destination": bpy.data.collections["shot"],
        "settings": {"payload_policy": "load_none"},
    }
    config = _config(handle)
    assert config.settings.payload_policy is PayloadPolicy.LOAD_NONE


def test_a_scenes_bindings(bindings: Bindings, tmp_path: Path) -> None:
    first = binding_on_file(bindings, _scene(), _root(tmp_path))
    attached = bindings.create_binding(_scene(), "shot")
    other = bpy.data.scenes.new("Other")
    assert bindings.in_scene(_scene()) == [first, attached]
    assert bindings.in_scene(other) == []
    assert _index().destinations.keys() == {first.binding_id, attached.binding_id}


def test_records_survive_save_and_reopen(bindings: Bindings, tmp_path: Path) -> None:
    # STATE-01: keys, identifiers, destinations, and settings survive independently of runtime attachments.
    with source_access.binding_state(tmp_path) as scene:
        first = bindings.create_binding(_scene(), "first", payload_policy=PayloadPolicy.LOAD_NONE, name="F")
        second = bindings.create_binding(_scene(), scene.key, name="A")
        bindings.attach("first", scene.caller)
        bindings.attach(scene.key, scene.caller)
        identifier = scene.caller.GetRootLayer().identifier
    save_and_reopen(tmp_path / "bindings.blend")
    f, a = bpy.data.collections["F"], bpy.data.collections["A"]
    assert _config(first) == BindingConfig(
        "first", RequestedSettings(PayloadPolicy.LOAD_NONE), root_layer_identifier=identifier, destination=f
    )
    assert _config(second) == BindingConfig(
        "shot", RequestedSettings(PayloadPolicy.LOAD_ALL), root_layer_identifier=identifier, destination=a
    )
    assert bindings.in_scene(_scene()) == [first, second]
    assert _destination_tag(f) == DestinationTag(first.binding_id, _scene())
    assert _destination_tag(a) == DestinationTag(second.binding_id, _scene())
    assert _index() == BindingIndex({first.binding_id: f, second.binding_id: a})


@pytest.mark.parametrize("key", ["", None, 7, Path("shot.usda")])
def test_creation_rejects_invalid_keys_before_writing(bindings: Bindings, key: object) -> None:
    before = (set(bpy.data.collections.keys()), set(bpy.data.texts.keys()), records.keys(_scene()))
    with pytest.raises(ValueError, match="nonempty string"):
        bindings.create_binding(_scene(), key)  # ty: ignore[invalid-argument-type]
    assert (set(bpy.data.collections.keys()), set(bpy.data.texts.keys()), records.keys(_scene())) == before
    assert bindings.in_scene(_scene()) == []


def test_a_path_like_key_is_used_literally(bindings: Bindings) -> None:
    handle = bindings.create_binding(_scene(), "//shot.usda")
    assert _config(handle).source_key == "//shot.usda"
    assert handle.live_stage() is None


def test_an_unreadable_index_stops_creation_before_any_change(bindings: Bindings, tmp_path: Path) -> None:
    binding_on_file(bindings, _scene(), _root(tmp_path))
    [text] = binding_records.index_texts()
    text[NAMESPACE][binding_records.INDEX_KEY] = {records.VERSION_KEY: 99}
    collections = len(bpy.data.collections)
    with pytest.raises(RefusedRecordError):
        binding_on_file(bindings, _scene(), _root(tmp_path / "other"))
    assert len(bpy.data.collections) == collections
    assert len(bindings.in_scene(_scene())) == 1


def test_two_indexes_stop_creation(bindings: Bindings, tmp_path: Path) -> None:
    # Copies the canonical-candidate rule can't decide between; repairing them is not creation's job.
    binding_on_file(bindings, _scene(), _root(tmp_path))
    [text] = binding_records.index_texts()
    text.copy()  # ID.copy copies the ID properties, the index record with them
    assert len(binding_records.index_texts()) == 2
    collections = len(bpy.data.collections)
    with pytest.raises(ValueError, match="2 binding indexes"):
        binding_on_file(bindings, _scene(), _root(tmp_path / "other"))
    assert len(bpy.data.collections) == collections
    assert len(bindings.in_scene(_scene())) == 1


def test_settings_change_only_their_binding(bindings: Bindings, tmp_path: Path) -> None:
    # BIND-10: configurations of independent bindings on the same source stay separate.
    with source_access.multi_binding(tmp_path) as scene:
        root = scene.roots[".usda"]
        changed, other = binding_on_file(bindings, _scene(), root), binding_on_file(bindings, _scene(), root)
        attached = bindings.create_binding(_scene(), "shot")
        bindings.attach("shot", scene.caller)
        before = [_config(h) for h in (other, attached)]
        changed.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
        assert [_config(h) for h in (other, attached)] == before
        assert _config(changed).settings.payload_policy is PayloadPolicy.LOAD_NONE


# Handles across undo, redo, and save/reopen.


def test_handles_survive_undo_redo_and_reopen(bindings: Bindings, tmp_path: Path) -> None:
    # API-01: a handle holds only the identifier, so nothing it holds goes stale. On F-BINDING-STATE.
    undo.require_global_undo()
    with source_access.binding_state(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root)
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
    assert handle.live_stage() is None
    bindings.attach(_config(handle).source_key, open_fresh(scene.root))
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)


def test_handles_on_f_binding_state(bindings: Bindings, tmp_path: Path) -> None:
    # API-02, API-03, API-07: synchronizing changes no setting and retains the attached live stage;
    # set_settings and reload record or reread without synchronizing.
    with source_access.binding_state(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root)
        before = _config(handle)
        assert handle.synchronize(Usd.TimeCode.Default()) == Result(ResultState.SUCCESS)
        assert _config(handle) == before  # API-02
        live = handle.live_stage()
        assert live is not None and live != scene.caller
        assert handle.synchronize(3) == Result(ResultState.SUCCESS)
        assert handle.live_stage() == live  # the same attachment after a second refresh
        assert handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE) == Result(ResultState.SUCCESS)
        assert handle.requested_settings().payload_policy is PayloadPolicy.LOAD_NONE  # API-03
        assert live.GetLoadSet()  # not applied: nothing synchronized
        assert binding_state.read_last_attempt(_scene(), handle.binding_id) is None
        assert handle.reload() == Result(ResultState.SUCCESS)
        assert handle.requested_settings().payload_policy is PayloadPolicy.LOAD_NONE  # API-07
        assert handle.live_stage() == live
        assert handle.synchronize(3) == Result(ResultState.SUCCESS)
        assert live.GetLoadSet()  # the caller's load set is protected
        stages = bindings.stages.get(handle.binding_id)
        assert stages is not None and stages.evaluation_stage is not None
        assert not stages.evaluation_stage.GetLoadSet()  # the binding's policy was applied


def test_undoing_creation_makes_handles_raise(bindings: Bindings, tmp_path: Path) -> None:
    # API-06: the binding is gone, so every method of its handles raises, as does one made afterwards;
    # redo brings it back. On F-BINDING-STATE.
    undo.require_global_undo()
    undo.push("base")
    with source_access.binding_state(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root)
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
            with pytest.raises(BindingNotFoundError):
                call()
    undo.redo()
    assert handle.synchronize(0) == Result(ResultState.SUCCESS)


# Reopening.


def test_reopening_synchronizes_nothing(bindings: Bindings, extension: ModuleType, tmp_path: Path) -> None:
    # REOPEN-02, SRC-03: reopening releases the attachment and does not open a stage.
    # The helper's caller stage is held only by the binding, so reopening must release its layers.
    root = _root(tmp_path)
    handle = binding_on_file(bindings, _scene(), root)
    handle.synchronize(0)
    assert handle.live_stage() is not None
    save_and_reopen(tmp_path / "reopen.blend")
    gc.collect()
    assert handle.live_stage() is None
    assert not Sdf.Layer.Find(str(root))
    assert extension.addon.is_registered()


def test_reopening_f_binding_state_synchronizes_nothing(
    bindings: Bindings, extension: ModuleType, tmp_path: Path
) -> None:
    # REOPEN-02, SRC-03 on F-BINDING-STATE: no synchronization runs, so the binding has no source stage,
    # and its published generation and last attempt are as saved. Nothing writes them before M5, so the
    # test does. Its caller's stage keeps the root layer open, so the registry is the evidence.
    with source_access.binding_state(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root, name="Shot")
        handle.synchronize(0)
        generation = Generation(handle.binding_id, PayloadPolicy.LOAD_ALL, 0.0, ())
        attempt = LastAttempt(PayloadPolicy.LOAD_ALL, 0.0, ResultState.SUCCESS, ())
        binding_state.write_generation(bpy.data.collections["Shot"], generation)
        binding_state.write_last_attempt(_scene(), handle.binding_id, attempt)
        save_and_reopen(tmp_path / "reopen.blend")
        assert bindings.stages.get(handle.binding_id) is None
        assert handle.live_stage() is None
        assert binding_state.read_generation(bpy.data.collections["Shot"]) == Loaded(generation, 1)
        assert binding_state.read_last_attempt(_scene(), handle.binding_id) == Loaded(attempt, 1)


def test_an_attached_source_is_unavailable_after_reopening(
    bindings: Bindings, extension: ModuleType, tmp_path: Path
) -> None:
    # SRC-03: until the caller attaches a stage again.
    handle = bindings.create_binding(_scene(), "shot")
    with source_access.reattach(tmp_path) as scene:
        bindings.attach("shot", scene.caller)
        assert handle.synchronize(0) == Result(ResultState.SUCCESS)
        save_and_reopen(tmp_path / "reopen.blend")
        result = handle.synchronize(0)
        assert result.state is ResultState.FATAL_FAILURE
        assert [d.category for d in result.diagnostics] == [DiagnosticCategory.UNAVAILABLE_SOURCE]
        assert bindings.attach("shot", scene.caller).attached == (handle.binding_id,)
        assert handle.synchronize(0) == Result(ResultState.SUCCESS)


# A configuration that can't be read.


@pytest.mark.parametrize("name", ["newer", "no-key", "unknown-policy", "unknown-field", "no-settings"])
def test_an_unsupported_configuration_is_kept_and_refuses(bindings: Bindings, tmp_path: Path, name: str) -> None:
    # SCHEMA-03: F-SCHEMA-VERSIONS' binding configurations, as another extension version or damage left them.
    with record_fixtures.schema_versions(tmp_path) as versions:
        stored = versions.bindings[name]
        handle = BindingHandle(binding_records.new_identifier())
        _scene()[NAMESPACE] = {binding_records.config_key(handle.binding_id): stored}
        for result in (
            handle.synchronize(0),
            handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE),
            handle.reload(),
        ):
            assert result.state is ResultState.FATAL_FAILURE
            [diagnostic] = result.diagnostics
            assert (diagnostic.category, diagnostic.severity) == (DiagnosticCategory.UNSUPPORTED_RECORD, Severity.ERROR)
            refused = records.load(binding_records.CONFIG, stored)
            assert isinstance(refused, records.RefusedRecord)
            assert refused.refusal is versions.bindings_refused[name]
            assert diagnostic.message == refused.message
        with pytest.raises(RefusedRecordError):
            handle.requested_settings()
        assert bindings.in_scene(_scene()) == [handle]
        assert records.stored(_scene(), binding_records.config_key(handle.binding_id)) == stored


@pytest.mark.parametrize("name", ["newer", "no-key", "unknown-policy", "unknown-field", "no-settings"])
def test_a_configuration_write_refuses_an_unsupported_one(bindings: Bindings, tmp_path: Path, name: str) -> None:
    # SCHEMA-03: the runtime write refuses every refusal, including those at the current version, which
    # records.write alone lets through.
    with record_fixtures.schema_versions(tmp_path) as versions:
        stored = versions.bindings[name]
        binding_id = binding_records.new_identifier()
        _scene()[NAMESPACE] = {binding_records.config_key(binding_id): stored}
        with pytest.raises(RefusedRecordError):
            runtime.set_config(binding_id, BindingConfig("shot", RequestedSettings(PayloadPolicy.LOAD_ALL)))
        assert records.stored(_scene(), binding_records.config_key(binding_id)) == stored


# The source key contract (source-access.md#source-identity).


def test_a_key_attaches_every_binding_with_it(bindings: Bindings, tmp_path: Path) -> None:
    # SID-03: two bindings share a key; a third has another.
    a, b = bindings.create_binding(_scene(), "shot"), bindings.create_binding(_scene(), "shot")
    c = bindings.create_binding(_scene(), "other")
    with source_access.reattach(tmp_path) as scene:
        assert bindings.attach("shot", scene.caller) == AttachResult(
            attached=(a.binding_id, b.binding_id), unconfirmed=()
        )
        assert [h.live_stage() for h in (a, b, c)] == [scene.caller, scene.caller, None]


def test_reattachment_needs_an_exact_key(bindings: Bindings, tmp_path: Path) -> None:
    # SID-04: case and whitespace count.
    handle = bindings.create_binding(_scene(), "shot")
    with source_access.reattach(tmp_path) as scene:
        for key in ("Shot", " shot", "shot "):
            assert bindings.attach(key, scene.caller) == AttachResult(attached=(), unconfirmed=())
        assert handle.live_stage() is None


def test_the_root_layer_never_finds_a_binding(bindings: Bindings, tmp_path: Path) -> None:
    # SID-05: the stored root layer matches, the key doesn't.
    handle = bindings.create_binding(_scene(), "shot")
    with source_access.reattach(tmp_path) as scene:
        bindings.attach("shot", scene.caller)
        assert bindings.attach("other", scene.same_root).attached == ()
        assert handle.live_stage() == scene.caller


def test_a_source_key_that_names_an_existing_file_does_not_acquire_it(bindings: Bindings, tmp_path: Path) -> None:
    # SRC-09: a key is only a name, even when it equals the identifier of an open, available stage.
    with source_access.reattach(tmp_path) as scene:
        key = scene.caller.GetRootLayer().identifier
        handle = bindings.create_binding(_scene(), key)
        before = _config(handle)
        for result in (handle.synchronize(0), handle.reload()):
            assert result.state is ResultState.FATAL_FAILURE
            assert [d.category for d in result.diagnostics] == [DiagnosticCategory.UNAVAILABLE_SOURCE]
        assert handle.live_stage() is None
        assert _config(handle) == before
        assert bindings.attach(key, scene.caller).attached == (handle.binding_id,)
        assert handle.live_stage() == scene.caller
        assert handle.synchronize(0) == Result(ResultState.SUCCESS)


def test_a_stage_over_the_same_root_layer_reattaches(bindings: Bindings, tmp_path: Path) -> None:
    handle = bindings.create_binding(_scene(), "shot")
    with source_access.reattach(tmp_path) as scene:
        bindings.attach("shot", scene.caller)
        assert bindings.attach("shot", scene.same_root).attached == (handle.binding_id,)
        assert handle.live_stage() == scene.same_root


def test_a_different_root_layer_needs_confirmation(bindings: Bindings, tmp_path: Path) -> None:
    # SID-06: without confirmation nothing changes for any binding with the key; with it, the stored
    # identifier becomes the new stage's, in the records.
    a, b = bindings.create_binding(_scene(), "shot"), bindings.create_binding(_scene(), "shot")
    with source_access.reattach(tmp_path) as scene:
        bindings.attach("shot", scene.caller)
        c = bindings.create_binding(_scene(), "shot")  # unattached, no stored root layer
        refused = bindings.attach("shot", scene.other_root)
        assert refused == AttachResult(attached=(), unconfirmed=(a.binding_id, b.binding_id))
        assert [h.live_stage() for h in (a, b, c)] == [scene.caller, scene.caller, None]
        caller = scene.caller.GetRootLayer().identifier
        assert [_config(h).root_layer_identifier for h in (a, b, c)] == [caller, caller, None]
        confirmed = bindings.attach("shot", scene.other_root, confirm=True)
        assert confirmed == AttachResult(attached=(a.binding_id, b.binding_id, c.binding_id), unconfirmed=())
        identifier = scene.other_root.GetRootLayer().identifier
        assert [_config(h).root_layer_identifier for h in (a, b, c)] == [identifier] * 3
        assert [h.live_stage() for h in (a, b, c)] == [scene.other_root] * 3


def test_the_stored_identifier_is_the_records_after_undo(bindings: Bindings, tmp_path: Path) -> None:
    # The confirmation rule reads the record, so undoing an attach's record change brings the old identifier back.
    undo.require_global_undo()
    handle = bindings.create_binding(_scene(), "shot")
    with source_access.reattach(tmp_path) as scene:
        bindings.attach("shot", scene.caller)
        undo.push("base")
        bindings.attach("shot", scene.other_root, confirm=True)
        undo.push("replace")
        undo.undo()
        assert _config(handle).root_layer_identifier == scene.caller.GetRootLayer().identifier
        assert bindings.attach("shot", scene.same_root).attached == (handle.binding_id,)  # needs no confirmation


def test_attach_uses_the_key_and_never_the_destination_name(bindings: Bindings, tmp_path: Path) -> None:
    handle = bindings.create_binding(_scene(), "other", name="shot")
    with source_access.reattach(tmp_path) as scene:
        assert bindings.attach("shot", scene.caller) == AttachResult(attached=(), unconfirmed=())
        assert handle.live_stage() is None


def _with_key(stored: object, key: str) -> dict[str, object]:
    """A stored attached-source configuration with this key."""
    assert isinstance(stored, dict)
    return stored | {"source_key": key}


def test_attach_skips_a_configuration_it_cannot_read(bindings: Bindings, tmp_path: Path) -> None:
    with record_fixtures.schema_versions(tmp_path) as versions:
        unreadable = _with_key(versions.bindings["newer"], "shot")
        _scene()[NAMESPACE] = {binding_records.config_key(binding_records.new_identifier()): unreadable}
        with source_access.reattach(tmp_path / "caller") as scene:
            assert bindings.attach("shot", scene.caller) == AttachResult(attached=(), unconfirmed=())


# The records' namespace.


@pytest.mark.parametrize("id_type", addon.RECORD_TYPES, ids=lambda t: t.__name__)
def test_the_namespace_is_registered_so_the_panel_hides_it(extension: ModuleType, id_type: type[bpy.types.ID]) -> None:
    # The Custom Properties panel skips properties the Python API defines (rna_prop_ui.draw).
    runtime = {p.identifier for p in id_type.bl_rna.properties if p.is_runtime}
    assert NAMESPACE in runtime


def test_records_stay_readable_with_the_extension_unregistered(bindings: Bindings, tmp_path: Path) -> None:
    # The records are raw ID properties, readable without the namespace's registered class; the API is not,
    # since its in-memory state needs the extension's handlers.
    handle = binding_on_file(bindings, _scene(), _root(tmp_path))
    handle.set_settings(payload_policy=PayloadPolicy.LOAD_NONE)
    expected = _config(handle)
    addon.unregister()
    save_and_reopen(tmp_path / "unregistered.blend")
    assert _config(handle) == replace(expected, destination=bpy.data.collections["root"])
    with pytest.raises(runtime.NotRegisteredError):
        handle.requested_settings()
