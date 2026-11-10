"""A binding's published generation and last attempt as records (lifecycle.md#binding-state).

Nothing writes them before M5's synchronization transaction, so these tests write them directly,
on bindings the synchronization API makes on a fresh process state per test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import source_access
from proscenium.binding.persistence import binding_records, binding_state, id_property_records, manifests
from proscenium.binding.persistence.binding_state import GenerationMetadata, LastSynchronizationAttempt
from proscenium.binding.persistence.id_property_records import (
    NAMESPACE,
    VERSION_KEY,
    LoadedRecord,
    RefusalReason,
    RefusedRecord,
    RefusedRecordError,
)
from proscenium.binding.persistence.manifests import Manifest
from proscenium.binding.results import Diagnostic, DiagnosticCode
from proscenium.binding.source_access.binding_settings import PayloadPolicy, RequestedSettings, new_settings
from proscenium.binding.source_access.stages import SourceRevision
from support.blend import save_and_reopen
from support.manifests import key, object_entry
from support.usd import binding_on_file

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.api.bindings import BindingHandle, Bindings

DIRTY = Diagnostic(
    DiagnosticCode.UNSAVED_LAYERS,
    "binding",
    "Displaying layers with unsaved edits",
    layer_identifiers=("/a.usda", "/b.usda"),
)
UNAVAILABLE = Diagnostic(DiagnosticCode.NO_ATTACHED_STAGE, "binding", "No stage is attached")
REVISION = SourceRevision("a revision")
# Every setting off its default, so each round trip and comparison covers it.
SETTINGS = RequestedSettings(PayloadPolicy.LOAD_NONE, True, ("default", "guide"), ("render",))
STORED_SETTINGS = {
    "payload_policy": "load_none",
    "coordinate_conversion": True,
    "viewport_purposes": ["default", "guide"],
    "render_purposes": ["render"],
}


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _shot() -> bpy.types.Collection:
    return bpy.data.collections["Shot"]


def _binding(bindings: Bindings, tmp_path: Path) -> BindingHandle:
    with source_access.binding_state(tmp_path) as scene:
        return binding_on_file(bindings, _scene(), scene.root_layer_path, name="Shot")


def _generation(handle: BindingHandle, time: float | None = 12.5) -> GenerationMetadata:
    cached = (13.0, 14.5) if time is not None else ()  # a generation at the default time code caches nothing
    return GenerationMetadata(handle.binding_id, SETTINGS, 0.01, time, REVISION, (DIRTY,), cached)


def _attempt(time: float | None = 20.0) -> LastSynchronizationAttempt:
    return LastSynchronizationAttempt(new_settings(PayloadPolicy.LOAD_ALL), time, (UNAVAILABLE,))


@pytest.mark.parametrize("time", [12.5, None], ids=["numeric", "default"])
def test_records_survive_save_and_reopen(bindings: Bindings, tmp_path: Path, time: float | None) -> None:
    # Diagnostics come back with their enums and their layers as a tuple, and cached time codes as a tuple.
    handle = _binding(bindings, tmp_path)
    binding_state.write_generation(bpy.data.collections["Shot"], _generation(handle, time))
    binding_state.write_last_attempt(_shot(), _attempt(time))
    save_and_reopen(tmp_path / "state.blend")
    assert binding_state.read_generation(bpy.data.collections["Shot"]) == LoadedRecord(
        _generation(handle, time), binding_state.GENERATION.version
    )
    assert binding_state.read_last_attempt(_shot()) == LoadedRecord(_attempt(time), binding_state.ATTEMPT.version)
    assert destination_settings() == STORED_SETTINGS  # what the refusal cases change


def destination_settings() -> dict[str, object]:
    return _shot()[NAMESPACE][binding_state.GENERATION_KEY]["applied_settings"].to_dict()


def test_a_generation_stored_without_cached_time_codes_has_none(bindings: Bindings, tmp_path: Path) -> None:
    handle = _binding(bindings, tmp_path)
    destination = bpy.data.collections["Shot"]
    binding_state.write_generation(destination, _generation(handle))
    stored = destination[NAMESPACE][binding_state.GENERATION_KEY].to_dict()
    del stored["cached_time_codes"]
    destination[NAMESPACE][binding_state.GENERATION_KEY] = stored
    expected = GenerationMetadata(handle.binding_id, SETTINGS, 0.01, 12.5, REVISION, (DIRTY,))
    assert binding_state.read_generation(destination) == LoadedRecord(expected, binding_state.GENERATION.version)


def test_the_records_are_kept_apart(bindings: Bindings, tmp_path: Path) -> None:
    # Writing one leaves the configuration, the manifest, and the other unchanged.
    handle = _binding(bindings, tmp_path)
    destination = bpy.data.collections["Shot"]
    manifests.write_manifest(destination, Manifest({key("a"): object_entry(None, "/World")}))

    def stored() -> list[object]:
        return [
            id_property_records.stored(destination, binding_records.config_key(handle.binding_id)),
            id_property_records.stored(destination, manifests.MANIFEST_KEY),
            id_property_records.stored(destination, binding_state.GENERATION_KEY),
            id_property_records.stored(destination, binding_state.ATTEMPT_KEY),
        ]

    config, manifest, _, _ = stored()
    binding_state.write_last_attempt(_shot(), _attempt())
    assert stored()[:3] == [config, manifest, None]
    attempt = stored()[3]
    binding_state.write_generation(destination, _generation(handle))
    assert stored()[:2] + stored()[3:] == [config, manifest, attempt]
    generation = stored()[2]
    binding_state.write_last_attempt(_shot(), _attempt(30.0))
    assert stored()[:3] == [config, manifest, generation]
    assert bindings.in_scene(_scene()) == [handle]  # the attempt's key isn't taken for a binding


def test_the_last_attempt_needs_no_publication(bindings: Bindings, tmp_path: Path) -> None:
    _binding(bindings, tmp_path)
    binding_state.write_last_attempt(_shot(), _attempt())
    assert binding_state.read_generation(_shot()) is None
    assert binding_state.read_last_attempt(_shot()) == LoadedRecord(_attempt(), 1)


def test_a_full_copy_copies_the_generation_with_its_destination(bindings: Bindings, tmp_path: Path) -> None:
    handle = _binding(bindings, tmp_path)
    binding_state.write_generation(bpy.data.collections["Shot"], _generation(handle))
    window = bpy.context.window
    assert window is not None
    window.scene = _scene()
    bpy.ops.scene.new(type="FULL_COPY")
    assert binding_state.read_generation(bpy.data.collections["Shot.001"]) == LoadedRecord(
        _generation(handle), binding_state.GENERATION.version
    )


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        ({VERSION_KEY: binding_state.GENERATION.version + 1}, RefusalReason.NEWER),
        ({"applied_settings": STORED_SETTINGS | {"payload_policy": "load_some"}}, RefusalReason.INVALID),
        ({"applied_settings": STORED_SETTINGS | {"render_purposes": ["preview"]}}, RefusalReason.INVALID),
        ({"applied_settings": {"payload_policy": "load_none"}}, RefusalReason.INVALID),  # without the other settings
        ({"unit_scale": 0.0}, RefusalReason.INVALID),
        ({"unit_scale": "one"}, RefusalReason.INVALID),
        ({"time_code": "twelve"}, RefusalReason.INVALID),
        ({"cached_time_codes": [14.5, 13.0]}, RefusalReason.INVALID),
        ({"cached_time_codes": [12.5, 13.0]}, RefusalReason.INVALID),
        ({"time_code": None}, RefusalReason.INVALID),  # cached time codes, without a time code to vary from
        (
            {"diagnostics": [{"category": "nonsense", "severity": "info", "message": "m", "layers": []}]},
            RefusalReason.INVALID,
        ),
    ],
)
def test_a_generation_that_cannot_be_read_is_refused_and_kept(
    bindings: Bindings, tmp_path: Path, change: dict[str, object], refusal: RefusalReason
) -> None:
    handle = _binding(bindings, tmp_path)
    destination = bpy.data.collections["Shot"]
    binding_state.write_generation(destination, _generation(handle))
    stored = destination[NAMESPACE][binding_state.GENERATION_KEY].to_dict() | change
    destination[NAMESPACE][binding_state.GENERATION_KEY] = stored
    result = binding_state.read_generation(destination)
    assert isinstance(result, RefusedRecord)
    assert result.refusal is refusal
    assert destination[NAMESPACE][binding_state.GENERATION_KEY].to_dict() == stored
    if refusal is RefusalReason.NEWER:  # writing refuses what the version shows; the rest, writers read first
        with pytest.raises(RefusedRecordError):
            binding_state.write_generation(destination, _generation(handle))
        assert destination[NAMESPACE][binding_state.GENERATION_KEY].to_dict() == stored
