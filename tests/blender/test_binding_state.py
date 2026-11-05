"""A binding's published generation and last attempt as records (lifecycle.md#binding-state).

Nothing writes them before M5's synchronization transaction, so these tests write them directly,
on bindings the synchronization API makes on a fresh process state per test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import source_access
from proscenium.binding.persistence import Manifest, binding_records, binding_state, manifests, records
from proscenium.binding.persistence.binding_state import Generation, LastAttempt
from proscenium.binding.persistence.records import (
    NAMESPACE,
    VERSION_KEY,
    Loaded,
    RefusalReason,
    RefusedRecord,
    RefusedRecordError,
)
from proscenium.binding.results import Diagnostic, DiagnosticCode
from proscenium.binding.source_access import PayloadPolicy, SourceRevision
from support.blend import save_and_reopen
from support.manifests import key, object_entry
from support.usd import binding_on_file

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.api.bindings import BindingHandle, Bindings

DIRTY = Diagnostic(
    DiagnosticCode.UNSAVED_LAYERS, "binding", "Displaying layers with unsaved edits", layers=("/a.usda", "/b.usda")
)
UNAVAILABLE = Diagnostic(DiagnosticCode.NO_ATTACHED_STAGE, "binding", "No stage is attached")
REVISION = SourceRevision("a revision")


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _binding(bindings: Bindings, tmp_path: Path) -> BindingHandle:
    with source_access.binding_state(tmp_path) as scene:
        return binding_on_file(bindings, _scene(), scene.root, name="Shot")


def _generation(handle: BindingHandle, time: float | None = 12.5) -> Generation:
    cached = (13.0, 14.5) if time is not None else ()  # a generation at the default time code caches nothing
    return Generation(handle.binding_id, PayloadPolicy.LOAD_NONE, time, REVISION, (DIRTY,), cached)


def _attempt(time: float | None = 20.0) -> LastAttempt:
    return LastAttempt(PayloadPolicy.LOAD_ALL, time, (UNAVAILABLE,))


@pytest.mark.parametrize("time", [12.5, None], ids=["numeric", "default"])
def test_records_survive_save_and_reopen(bindings: Bindings, tmp_path: Path, time: float | None) -> None:
    # Diagnostics come back with their enums and their layers as a tuple, and cached time codes as a tuple.
    handle = _binding(bindings, tmp_path)
    binding_state.write_generation(bpy.data.collections["Shot"], _generation(handle, time))
    binding_state.write_last_attempt(_scene(), handle.binding_id, _attempt(time))
    save_and_reopen(tmp_path / "state.blend")
    assert binding_state.read_generation(bpy.data.collections["Shot"]) == Loaded(_generation(handle, time), 1)
    assert binding_state.read_last_attempt(_scene(), handle.binding_id) == Loaded(_attempt(time), 1)


def test_a_generation_stored_without_cached_time_codes_has_none(bindings: Bindings, tmp_path: Path) -> None:
    handle = _binding(bindings, tmp_path)
    destination = bpy.data.collections["Shot"]
    binding_state.write_generation(destination, _generation(handle))
    stored = destination[NAMESPACE][binding_state.GENERATION_KEY].to_dict()
    del stored["cached_time_codes"]
    destination[NAMESPACE][binding_state.GENERATION_KEY] = stored
    expected = Generation(handle.binding_id, PayloadPolicy.LOAD_NONE, 12.5, REVISION, (DIRTY,))
    assert binding_state.read_generation(destination) == Loaded(expected, 1)


def test_the_records_are_kept_apart(bindings: Bindings, tmp_path: Path) -> None:
    # Writing one leaves the configuration, the manifest, and the other unchanged.
    handle = _binding(bindings, tmp_path)
    destination = bpy.data.collections["Shot"]
    manifests.write_manifest(destination, Manifest({key("a"): object_entry(None, "/World")}))

    def stored() -> list[object]:
        return [
            records.stored(_scene(), binding_records.config_key(handle.binding_id)),
            records.stored(destination, manifests.MANIFEST_KEY),
            records.stored(destination, binding_state.GENERATION_KEY),
            records.stored(_scene(), binding_state.ATTEMPT_PREFIX + handle.binding_id),
        ]

    config, manifest, _, _ = stored()
    binding_state.write_last_attempt(_scene(), handle.binding_id, _attempt())
    assert stored()[:3] == [config, manifest, None]
    attempt = stored()[3]
    binding_state.write_generation(destination, _generation(handle))
    assert stored()[:2] + stored()[3:] == [config, manifest, attempt]
    generation = stored()[2]
    binding_state.write_last_attempt(_scene(), handle.binding_id, _attempt(30.0))
    assert stored()[:3] == [config, manifest, generation]
    assert bindings.in_scene(_scene()) == [handle]  # the attempt's key isn't taken for a binding


def test_the_last_attempt_needs_no_destination(bindings: Bindings, tmp_path: Path) -> None:
    handle = _binding(bindings, tmp_path)
    bpy.data.collections.remove(bpy.data.collections["Shot"])
    binding_state.write_last_attempt(_scene(), handle.binding_id, _attempt())
    assert binding_state.read_last_attempt(_scene(), handle.binding_id) == Loaded(_attempt(), 1)


def test_a_full_copy_copies_the_generation_with_its_destination(bindings: Bindings, tmp_path: Path) -> None:
    handle = _binding(bindings, tmp_path)
    binding_state.write_generation(bpy.data.collections["Shot"], _generation(handle))
    window = bpy.context.window
    assert window is not None
    window.scene = _scene()
    bpy.ops.scene.new(type="FULL_COPY")
    assert binding_state.read_generation(bpy.data.collections["Shot.001"]) == Loaded(_generation(handle), 1)


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        ({VERSION_KEY: 2}, RefusalReason.NEWER),
        ({"payload_policy": "load_some"}, RefusalReason.INVALID),
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
