"""The pending-cleanup ledger on the binding index's Text, its write-through, and the cleanup status read from it.

See lifecycle.md#pending-cleanup and pipeline.md#diagnostics.

Bindings come from the synchronization API on a fresh process state per test; the resources the ledger tracks are made
here, as preparation makes them.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import schema_version_cases as record_fixtures
from fixtures.scenes import Scene, copy_scene
from proscenium.binding import persistence, runtime
from proscenium.binding.persistence import cleanup_ledgers
from proscenium.binding.persistence.cleanup_ledgers import Ledger, LedgerEntry, OriginatingOperation
from proscenium.binding.persistence.id_property_records import (
    NAMESPACE,
    LoadedRecord,
    RefusalReason,
    RefusedRecord,
    RefusedRecordError,
)
from proscenium.binding.persistence.manifests import RepresentationRole
from proscenium.binding.results import Diagnostic, DiagnosticCode, ResultState
from proscenium.synchronization import preparation_resources
from support.blend import save_and_reopen
from support.manifests import key
from support.usd import binding_on_file

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.api.bindings import Bindings
    from proscenium.binding.source_access import BindingId


def _binding(bindings: Bindings) -> BindingId:
    return bindings.create_binding(bpy.data.scenes["Scene"]).binding_id


def _text() -> bpy.types.Text:
    [text] = persistence.binding_records.index_texts()
    return text


def _entries(binding_id: BindingId) -> dict[str, LedgerEntry]:
    """A bounds mesh retirement left and an object disposal left, by ledger key."""
    mesh = bpy.data.meshes.new("Leftover")
    obj = bpy.data.objects.new("Leftover", mesh)
    retired = Diagnostic(
        DiagnosticCode.RETIREMENT_FAILED,
        binding_id,
        "Couldn't retire",
        pending_resource_key=key("mesh"),
        role="bounds mesh",
    )
    disposed = Diagnostic(
        DiagnosticCode.DISPOSAL_FAILED,
        binding_id,
        "Couldn't dispose",
        pending_resource_key=key("object"),
        role="object",
    )
    synchronize = OriginatingOperation.SYNCHRONIZE
    return {
        key("mesh"): LedgerEntry(binding_id, key("m"), RepresentationRole.BOUNDS_MESH, mesh, synchronize, retired),
        key("object"): LedgerEntry(binding_id, key("o"), RepresentationRole.OBJECT, obj, synchronize, disposed),
    }


def test_a_ledger_survives_save_and_reopen(bindings: Bindings, tmp_path: Path) -> None:
    # PEND-06, STATE-04: on the binding index's Text, each entry's binding, entry key, role, pointer, operation, and
    # cleanup diagnostic, each its own field.
    binding_id = _binding(bindings)
    entries = _entries(binding_id)
    runtime.pending_cleanup.set_ledger_entries(entries)
    save_and_reopen(tmp_path / "ledger.blend")
    mesh, obj = bpy.data.meshes["Leftover"], bpy.data.objects["Leftover"]
    expected = {
        key("mesh"): replace(entries[key("mesh")], datablock=mesh),
        key("object"): replace(entries[key("object")], datablock=obj),
    }
    read = cleanup_ledgers.read_ledger(_text())
    assert read == LoadedRecord(Ledger(expected), 1)
    assert runtime.pending_cleanup.ledger() == read
    assert all(type(e.role) is RepresentationRole for e in read.record.entries.values())


def test_a_change_writes_only_its_entries(bindings: Bindings) -> None:
    binding_id = _binding(bindings)
    runtime.pending_cleanup.set_ledger_entries(_entries(binding_id))
    group = _text()[NAMESPACE][cleanup_ledgers.LEDGER_KEY]["entries"]
    kept = group[key("object")].to_dict()
    runtime.pending_cleanup.set_ledger_entries({}, [key("mesh")])
    assert list(group.keys()) == [key("object")]  # the stored group, changed in place
    assert group[key("object")].to_dict() == kept
    assert dict(runtime.pending_cleanup.ledger().record.entries).keys() == {key("object")}  # ty: ignore[unresolved-attribute]


def test_a_removed_datablock_leaves_an_entry_with_nothing_to_dispose_of(bindings: Bindings) -> None:
    binding_id = _binding(bindings)
    runtime.pending_cleanup.set_ledger_entries(_entries(binding_id))
    runtime.pending_cleanup.ledger()  # held
    bpy.data.objects.remove(bpy.data.objects["Leftover"])
    held = runtime.pending_cleanup.ledger()
    assert isinstance(held, LoadedRecord)
    assert held.record.entries[key("object")].datablock is None
    assert held.record.entries[key("mesh")].datablock == bpy.data.meshes["Leftover"]


def test_a_file_without_a_binding_index_has_no_ledger(bindings: Bindings) -> None:
    assert runtime.pending_cleanup.ledger() is None
    with pytest.raises(ValueError, match="no binding index"):
        runtime.pending_cleanup.set_ledger_entries({})


def test_two_binding_indexes_refuse_the_ledger(bindings: Bindings) -> None:
    # As appending another file's index Text makes it: nothing is recorded or disposed of until it's gone.
    binding_id = _binding(bindings)
    _text().copy()
    with pytest.raises(ValueError, match="2 binding indexes"):
        runtime.pending_cleanup.ledger()
    with pytest.raises(ValueError, match="2 binding indexes"):
        runtime.pending_cleanup.set_ledger_entries(_entries(binding_id))
    with pytest.raises(ValueError, match="2 binding indexes"):
        preparation_resources.new_preparation_resources(binding_id, OriginatingOperation.SYNCHRONIZE)
    assert runtime.pending_cleanup.cleanup_status(binding_id) == ()  # no ledger names what's pending
    assert all(cleanup_ledgers.LEDGER_KEY not in text[NAMESPACE] for text in persistence.binding_records.index_texts())


@pytest.mark.parametrize("name", ["newer", "no-version", "not-a-group"])  # F-SCHEMA-VERSIONS' ledgers
def test_a_ledger_that_cant_be_read_is_kept_and_refuses(bindings: Bindings, tmp_path: Path, name: str) -> None:
    # SCHEMA-04, SCHEMA-06 on F-SCHEMA-VERSIONS' "unsupported-ledger": refused whatever its fields, never replaced, and
    # no work is prepared, since the ledger couldn't track it.
    with record_fixtures.schema_versions(tmp_path) as versions:
        binding_id = _binding(bindings)
        _text()[NAMESPACE][cleanup_ledgers.LEDGER_KEY] = versions.ledgers[name]
        stored = _stored()
        refused = cleanup_ledgers.read_ledger(_text())
        assert isinstance(refused, RefusedRecord)
        assert refused.refusal is versions.ledgers_refused[name]
        assert runtime.pending_cleanup.ledger() == refused
        assert runtime.pending_cleanup.cleanup_status(binding_id) == ()
        with pytest.raises(RefusedRecordError):
            runtime.pending_cleanup.set_ledger_entries(_entries(binding_id))
        with pytest.raises(RefusedRecordError):
            cleanup_ledgers.write_ledger_entries(_text(), Ledger(_entries(binding_id)), [key("mesh")], [])
        collections = len(bpy.data.collections)
        with pytest.raises(RefusedRecordError):
            preparation_resources.new_preparation_resources(binding_id, OriginatingOperation.SYNCHRONIZE)
        assert len(bpy.data.collections) == collections
        assert _stored() == stored


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"role": "hologram"}, "hologram"),
        ({"operation": "lost"}, "lost"),
        ({"diagnostic": None}, "cleanup diagnostic of its failed removal"),
        ({"binding_id": 7}, "names its binding"),
    ],
)
def test_an_invalid_ledger_is_refused(bindings: Bindings, change: dict[str, object], problem: str) -> None:
    binding_id = _binding(bindings)
    runtime.pending_cleanup.set_ledger_entries(_entries(binding_id))
    stored = _stored()
    stored["entries"][key("mesh")] |= change  # ty: ignore[not-subscriptable]
    _text()[NAMESPACE][cleanup_ledgers.LEDGER_KEY] = stored
    refused = runtime.pending_cleanup.ledger()
    assert isinstance(refused, RefusedRecord)
    assert refused.refusal is RefusalReason.INVALID
    assert problem in refused.message


def test_a_ledger_key_is_32_hex_digits(bindings: Bindings) -> None:
    binding_id = _binding(bindings)
    entry = next(iter(_entries(binding_id).values()))
    assert len(persistence.cleanup_ledgers.new_ledger_key()) == 32
    with pytest.raises(ValueError, match="ledger keys are 32 hex digits"):
        runtime.pending_cleanup.set_ledger_entries({"leftover": entry})
    assert runtime.pending_cleanup.ledger() is None


@pytest.mark.parametrize(
    ("removed", "problem"), [([key("mesh")], "both changes and removes"), ([key("gone")], "doesn't have")]
)
def test_an_update_that_makes_no_ledger_changes_nothing(bindings: Bindings, removed: list[str], problem: str) -> None:
    binding_id = _binding(bindings)
    entries = _entries(binding_id)
    runtime.pending_cleanup.set_ledger_entries(entries)
    stored = _stored()
    with pytest.raises(ValueError, match=problem):
        runtime.pending_cleanup.set_ledger_entries({key("mesh"): entries[key("mesh")]}, removed)
    assert _stored() == stored
    assert runtime.pending_cleanup.ledger() == LoadedRecord(Ledger(entries), 1)


def test_each_result_reports_its_bindings_cleanup_status(bindings: Bindings, tmp_path: Path) -> None:
    # DIAG-06, DIAG-15, API-13: the ledger's leftovers are in each result's cleanup status, apart from its own
    # diagnostics and leaving its state; another binding's leftovers aren't. From D6,
    # F-PREPARATION-CLEANUP-FAILURE checks it through the synchronizations that leave them.
    root = copy_scene(Scene.SOURCE_ACCESS, tmp_path) / "root.usda"
    handle = binding_on_file(bindings, bpy.data.scenes["Scene"], root)
    other = _binding(bindings)
    entries = _entries(handle.binding_id)
    others = {key("other"): _entries(other)[key("object")]}
    runtime.pending_cleanup.set_ledger_entries(entries | others)
    stage = handle.live_stage()
    assert stage is not None
    status = tuple(e.diagnostic for _, e in sorted(entries.items()))
    for result in (handle.synchronize(0), handle.attach(stage), handle.set_settings(), handle.reload()):
        assert (result.state, result.diagnostics, result.pending_cleanup_diagnostics) == (
            ResultState.SUCCESS,
            (),
            status,
        )
    # A refusal reports it too.
    refused = bindings.synchronize(other, 0)
    assert refused.state is ResultState.FATAL_FAILURE
    assert refused.pending_cleanup_diagnostics == (others[key("other")].diagnostic,)
    # Resolved work leaves the status.
    runtime.pending_cleanup.set_ledger_entries({}, list(entries))
    assert handle.synchronize(0).pending_cleanup_diagnostics == ()


def _stored() -> object:
    return persistence.id_property_records.stored(_text(), cleanup_ledgers.LEDGER_KEY)
