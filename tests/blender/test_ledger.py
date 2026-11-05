"""The pending-cleanup ledger on the binding index's Text, and its write-through (lifecycle.md#pending-cleanup).

Bindings come from the synchronization API on a fresh process state per test; the resources the ledger tracks are made
here, as preparation makes them.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import bpy
import pytest

from fixtures import records as record_fixtures
from proscenium.binding import persistence, runtime
from proscenium.binding.persistence import (
    Ledger,
    LedgerEntry,
    OriginatingOperation,
    RepresentationRole,
    RetryStatus,
    ledger,
)
from proscenium.binding.persistence.records import NAMESPACE, Loaded, RefusalReason, RefusedRecord, RefusedRecordError
from proscenium.binding.results import Diagnostic, DiagnosticCode
from proscenium.synchronization import prepared_work
from support.blend import save_and_reopen
from support.manifests import key

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.api.bindings import Bindings
    from proscenium.binding.source_access import BindingId


def _binding(bindings: Bindings) -> BindingId:
    return bindings.create_binding(bpy.data.scenes["Scene"]).binding_id


def _text() -> bpy.types.Text:
    [text] = persistence.index_texts()
    return text


def _entries(binding_id: BindingId) -> dict[str, LedgerEntry]:
    """A prepared mesh and a retryable object, by ledger key."""
    mesh = bpy.data.meshes.new("Leftover")
    obj = bpy.data.objects.new("Leftover", mesh)
    diagnostic = Diagnostic(
        DiagnosticCode.DISPOSAL_FAILED, binding_id, "Couldn't dispose", resource=key("object"), role="object"
    )
    prepared, retryable = RetryStatus.PREPARED, RetryStatus.RETRYABLE
    synchronize = OriginatingOperation.SYNCHRONIZE
    return {
        key("mesh"): LedgerEntry(binding_id, key("m"), RepresentationRole.BOUNDS_MESH, mesh, synchronize, prepared),
        key("object"): LedgerEntry(
            binding_id, key("o"), RepresentationRole.OBJECT, obj, synchronize, retryable, diagnostic
        ),
    }


def test_a_ledger_survives_save_and_reopen(bindings: Bindings, tmp_path: Path) -> None:
    # PEND-06, STATE-04: on the binding index's Text, each entry's binding, entry key, role, pointer, operation, retry
    # status, and cleanup diagnostic, each its own field.
    binding_id = _binding(bindings)
    entries = _entries(binding_id)
    runtime.set_ledger_entries(entries)
    save_and_reopen(tmp_path / "ledger.blend")
    mesh, obj = bpy.data.meshes["Leftover"], bpy.data.objects["Leftover"]
    expected = {
        key("mesh"): replace(entries[key("mesh")], datablock=mesh),
        key("object"): replace(entries[key("object")], datablock=obj),
    }
    read = ledger.read_ledger(_text())
    assert read == Loaded(Ledger(expected), 1)
    assert runtime.ledger() == read
    assert all(type(e.role) is RepresentationRole for e in read.record.entries.values())


def test_a_change_writes_only_its_entries(bindings: Bindings) -> None:
    binding_id = _binding(bindings)
    runtime.set_ledger_entries(_entries(binding_id))
    group = _text()[NAMESPACE][ledger.LEDGER_KEY]["entries"]
    kept = group[key("object")].to_dict()
    runtime.set_ledger_entries({}, [key("mesh")])
    assert list(group.keys()) == [key("object")]  # the stored group, changed in place
    assert group[key("object")].to_dict() == kept
    assert dict(runtime.ledger().record.entries).keys() == {key("object")}  # ty: ignore[unresolved-attribute]


def test_a_removed_datablock_leaves_an_entry_with_nothing_to_dispose_of(bindings: Bindings) -> None:
    binding_id = _binding(bindings)
    runtime.set_ledger_entries(_entries(binding_id))
    runtime.ledger()  # held
    bpy.data.objects.remove(bpy.data.objects["Leftover"])
    held = runtime.ledger()
    assert isinstance(held, Loaded)
    assert held.record.entries[key("object")].datablock is None
    assert held.record.entries[key("mesh")].datablock == bpy.data.meshes["Leftover"]


def test_a_file_without_a_binding_index_has_no_ledger(bindings: Bindings) -> None:
    assert runtime.ledger() is None
    with pytest.raises(ValueError, match="no binding index"):
        runtime.set_ledger_entries({})


def test_two_binding_indexes_refuse_the_ledger(bindings: Bindings) -> None:
    # As appending another file's index Text makes it: nothing is recorded or disposed of until it's gone.
    binding_id = _binding(bindings)
    _text().copy()
    runtime.invalidate()  # the records changed behind the state, as an append changes them
    with pytest.raises(ValueError, match="2 binding indexes"):
        runtime.ledger()
    with pytest.raises(ValueError, match="2 binding indexes"):
        runtime.set_ledger_entries(_entries(binding_id))
    with pytest.raises(ValueError, match="2 binding indexes"):
        prepared_work.new_prepared_work(binding_id, OriginatingOperation.SYNCHRONIZE)
    assert all(ledger.LEDGER_KEY not in text[NAMESPACE] for text in persistence.index_texts())


@pytest.mark.parametrize("name", ["newer", "no-version", "not-a-group"])  # F-SCHEMA-VERSIONS' ledgers
def test_a_ledger_that_cant_be_read_is_kept_and_refuses(bindings: Bindings, tmp_path: Path, name: str) -> None:
    # SCHEMA-04, SCHEMA-06 on F-SCHEMA-VERSIONS' "unsupported-ledger": refused whatever its fields, never replaced, and
    # no work is prepared, since the ledger couldn't track it.
    with record_fixtures.schema_versions(tmp_path) as versions:
        binding_id = _binding(bindings)
        _text()[NAMESPACE][ledger.LEDGER_KEY] = versions.ledgers[name]
        stored = _stored()
        runtime.invalidate()  # the record changed behind the state, as a load or undo changes it
        refused = ledger.read_ledger(_text())
        assert isinstance(refused, RefusedRecord)
        assert refused.refusal is versions.ledgers_refused[name]
        assert runtime.ledger() == refused
        with pytest.raises(RefusedRecordError):
            runtime.set_ledger_entries(_entries(binding_id))
        with pytest.raises(RefusedRecordError):
            ledger.write_ledger_entries(_text(), Ledger(_entries(binding_id)), [key("mesh")], [])
        collections = len(bpy.data.collections)
        with pytest.raises(RefusedRecordError):
            prepared_work.new_prepared_work(binding_id, OriginatingOperation.SYNCHRONIZE)
        assert len(bpy.data.collections) == collections
        assert _stored() == stored


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"role": "hologram"}, "hologram"),
        ({"status": "lost"}, "lost"),
        ({"status": "retryable", "diagnostic": None}, "a retryable entry has a cleanup diagnostic"),
        ({"binding_id": 7}, "names its binding"),
    ],
)
def test_an_invalid_ledger_is_refused(bindings: Bindings, change: dict[str, object], problem: str) -> None:
    binding_id = _binding(bindings)
    runtime.set_ledger_entries(_entries(binding_id))
    stored = _stored()
    stored["entries"][key("mesh")] |= change  # ty: ignore[not-subscriptable]
    _text()[NAMESPACE][ledger.LEDGER_KEY] = stored
    runtime.invalidate()
    refused = runtime.ledger()
    assert isinstance(refused, RefusedRecord)
    assert refused.refusal is RefusalReason.INVALID
    assert problem in refused.message


def test_a_ledger_key_is_32_hex_digits(bindings: Bindings) -> None:
    binding_id = _binding(bindings)
    entry = next(iter(_entries(binding_id).values()))
    assert len(persistence.new_ledger_key()) == 32
    with pytest.raises(ValueError, match="ledger keys are 32 hex digits"):
        runtime.set_ledger_entries({"leftover": entry})
    assert runtime.ledger() is None


@pytest.mark.parametrize(
    ("removed", "problem"), [([key("mesh")], "both changes and removes"), ([key("gone")], "doesn't have")]
)
def test_an_update_that_makes_no_ledger_changes_nothing(bindings: Bindings, removed: list[str], problem: str) -> None:
    binding_id = _binding(bindings)
    entries = _entries(binding_id)
    runtime.set_ledger_entries(entries)
    stored = _stored()
    with pytest.raises(ValueError, match=problem):
        runtime.set_ledger_entries({key("mesh"): entries[key("mesh")]}, removed)
    assert _stored() == stored
    assert runtime.ledger() == Loaded(Ledger(entries), 1)


def _stored() -> object:
    return persistence.records.stored(_text(), ledger.LEDGER_KEY)
