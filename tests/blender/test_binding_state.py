"""A binding's published generation and last attempt as records (lifecycle.md#binding-state).

Nothing writes them before M5's synchronization transaction, so these tests write them directly,
on bindings the synchronization API makes on a fresh process state per test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest
from pxr import Usd

from fixtures import source_access
from proscenium import binding_state, bindings, ownership, records, synchronization
from proscenium.binding_state import Generation, LastAttempt
from proscenium.bindings import PayloadPolicy
from proscenium.ownership import Manifest, ManifestEntry
from proscenium.records import NAMESPACE, VERSION_KEY, Loaded, RecordRefused, Refusal, Refused
from proscenium.results import Category, Diagnostic, ResultState, Severity
from proscenium.synchronization import BindingHandle, Synchronization
from support.blend import save_and_reopen

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

DIRTY = Diagnostic(Category.SOURCE_STATE, Severity.INFO, "Displaying layers with unsaved edits", ("/a.usda", "/b.usda"))
UNAVAILABLE = Diagnostic(Category.UNAVAILABLE_SOURCE, Severity.ERROR, "Can't open /shot.usda")


@pytest.fixture
def sync(monkeypatch: pytest.MonkeyPatch) -> Iterator[Synchronization]:
    fresh = Synchronization()
    monkeypatch.setattr(synchronization, "SYNCHRONIZATION", fresh)
    yield fresh


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _binding(sync: Synchronization, tmp_path: Path) -> BindingHandle:
    with source_access.binding_state(tmp_path) as scene:
        return sync.create_file_binding(_scene(), scene.root, name="Shot")


def _generation(handle: BindingHandle, time: float | None = 12.5) -> Generation:
    return Generation(handle.binding_id, PayloadPolicy.LOAD_NONE, time, (DIRTY,))


def _attempt(time: float | None = 20.0) -> LastAttempt:
    return LastAttempt(PayloadPolicy.LOAD_ALL, time, ResultState.FATAL_FAILURE, (UNAVAILABLE,))


@pytest.mark.parametrize("time", [12.5, None], ids=["numeric", "default"])
def test_records_survive_save_and_reopen(sync: Synchronization, tmp_path: Path, time: float | None) -> None:
    # Diagnostics come back with their enums and their layers as a tuple.
    handle = _binding(sync, tmp_path)
    binding_state.write_generation(bpy.data.collections["Shot"], _generation(handle, time))
    binding_state.write_last_attempt(_scene(), handle.binding_id, _attempt(time))
    save_and_reopen(tmp_path / "state.blend")
    assert binding_state.read_generation(bpy.data.collections["Shot"]) == Loaded(_generation(handle, time), 1)
    assert binding_state.read_last_attempt(_scene(), handle.binding_id) == Loaded(_attempt(time), 1)


def test_time_codes_are_stored_as_their_value_or_none(sync: Synchronization) -> None:
    # The default time code's value is NaN, which would make two equal records unequal.
    assert binding_state.stored_time(Usd.TimeCode.Default()) is None
    assert binding_state.time_code(None).IsDefault()
    assert binding_state.time_code(binding_state.stored_time(Usd.TimeCode(7.25))) == Usd.TimeCode(7.25)


def test_the_records_are_kept_apart(sync: Synchronization, tmp_path: Path) -> None:
    # Writing one leaves the configuration, the manifest, and the other unchanged.
    handle = _binding(sync, tmp_path)
    destination = bpy.data.collections["Shot"]
    ownership.write_manifest(destination, Manifest({"a": ManifestEntry(None, [], "prim", [])}))

    def stored() -> list[object]:
        return [
            records.stored(_scene(), bindings.config_key(handle.binding_id)),
            records.stored(destination, ownership.MANIFEST_KEY),
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
    assert sync.bindings(_scene()) == [handle]  # the attempt's key isn't taken for a binding


def test_the_last_attempt_needs_no_destination(sync: Synchronization, tmp_path: Path) -> None:
    handle = _binding(sync, tmp_path)
    bpy.data.collections.remove(bpy.data.collections["Shot"])
    binding_state.write_last_attempt(_scene(), handle.binding_id, _attempt())
    assert binding_state.read_last_attempt(_scene(), handle.binding_id) == Loaded(_attempt(), 1)


def test_a_full_copy_copies_the_generation_with_its_destination(sync: Synchronization, tmp_path: Path) -> None:
    handle = _binding(sync, tmp_path)
    binding_state.write_generation(bpy.data.collections["Shot"], _generation(handle))
    window = bpy.context.window
    assert window is not None
    window.scene = _scene()
    bpy.ops.scene.new(type="FULL_COPY")
    assert binding_state.read_generation(bpy.data.collections["Shot.001"]) == Loaded(_generation(handle), 1)


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        ({VERSION_KEY: 2}, Refusal.NEWER),
        ({"payload_policy": "load_some"}, Refusal.INVALID),
        ({"time_code": "twelve"}, Refusal.INVALID),
        (
            {"diagnostics": [{"category": "nonsense", "severity": "info", "message": "m", "layers": []}]},
            Refusal.INVALID,
        ),
    ],
)
def test_a_generation_that_cannot_be_read_is_refused_and_kept(
    sync: Synchronization, tmp_path: Path, change: dict[str, object], refusal: Refusal
) -> None:
    handle = _binding(sync, tmp_path)
    destination = bpy.data.collections["Shot"]
    binding_state.write_generation(destination, _generation(handle))
    stored = destination[NAMESPACE][binding_state.GENERATION_KEY].to_dict() | change
    destination[NAMESPACE][binding_state.GENERATION_KEY] = stored
    result = binding_state.read_generation(destination)
    assert isinstance(result, Refused)
    assert result.refusal is refusal
    with pytest.raises(RecordRefused):
        binding_state.write_generation(destination, _generation(handle))
    assert destination[NAMESPACE][binding_state.GENERATION_KEY].to_dict() == stored


def test_a_diagnostic_rejects_values_it_cannot_hold() -> None:
    with pytest.raises(ValueError, match="not a valid Category"):
        Diagnostic("nonsense", Severity.INFO, "m")  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError, match="message and layers are strings"):
        Diagnostic(Category.SOURCE_STATE, Severity.INFO, "m", (1,))  # ty: ignore[invalid-argument-type]
