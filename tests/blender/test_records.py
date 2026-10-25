"""Versioned records stored in ID properties (lifecycle.md#schema-versions).

F-SCHEMA-VERSIONS supplies the stored records and what loading each must give. They are stored
raw, as a file written by another extension version would hold them, since the extension itself
only writes current-version records. Loading them is tested in tests/bpy_free/test_record_loading.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import bpy
import pytest

from fixtures import records as fixture
from proscenium.persistence.records import (
    NAMESPACE,
    VERSION_KEY,
    Loaded,
    RefusedRecord,
    RefusedRecordError,
    Schema,
    read,
    write,
    write_items,
)
from support.blend import save_and_reopen

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@dataclass(frozen=True)
class Single:
    a: int


@pytest.fixture
def versions(tmp_path: Path) -> Iterator[fixture.SchemaVersions]:
    with fixture.schema_versions(tmp_path) as built:
        yield built


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes[0]


def _version(stored: object) -> int:
    assert isinstance(stored, dict)
    return stored[VERSION_KEY]


def _store_raw(versions: fixture.SchemaVersions) -> None:
    _scene()[NAMESPACE] = dict(versions.stored)


def _raw() -> dict[str, Any]:
    return _scene()[NAMESPACE].to_dict()


# Storage in ID properties.


@dataclass(frozen=True)
class Pointers:
    target: bpy.types.Collection
    by_id: dict[str, bpy.types.Collection]
    items: list[dict[str, int]]


POINTERS = Schema("pointers", version=1, record_type=Pointers)


def test_a_record_with_pointers_survives_save_and_reopen(tmp_path: Path) -> None:
    collection = bpy.data.collections.new("Dest")
    _scene().collection.children.link(collection)
    write(_scene(), "pointers", POINTERS, Pointers(collection, {"B1": collection}, [{"n": 1}]))
    save_and_reopen(tmp_path / "pointers.blend")
    collection = bpy.data.collections["Dest"]
    assert read(_scene(), "pointers", POINTERS) == Loaded(Pointers(collection, {"B1": collection}, [{"n": 1}]), 1)


def test_stored_records_survive_save_and_reopen_unchanged(versions: fixture.SchemaVersions, tmp_path: Path) -> None:
    _store_raw(versions)
    save_and_reopen(tmp_path / "versions.blend")
    assert _raw() == versions.stored


def test_reading_migrates_in_memory_and_changes_nothing(versions: fixture.SchemaVersions, tmp_path: Path) -> None:
    # SCHEMA-02: older records load at the current version; the stored ones stay as they were.
    _store_raw(versions)
    save_and_reopen(tmp_path / "versions.blend")
    for name, expected in versions.loaded.items():
        assert read(_scene(), name, versions.schema) == Loaded(expected, _version(versions.stored[name]))
    for name, refusal in versions.refused.items():
        result = read(_scene(), name, versions.schema)
        assert isinstance(result, RefusedRecord)
        assert result.refusal is refusal
    assert _raw() == versions.stored
    assert not bpy.data.is_dirty


@pytest.mark.parametrize("name", ["newer", "no-version", "not-a-group"])
def test_writing_never_replaces_a_newer_or_unreadable_record(versions: fixture.SchemaVersions, name: str) -> None:
    # SCHEMA-03, SCHEMA-04: what the stored version shows is refused without loading the record.
    _store_raw(versions)
    with pytest.raises(RefusedRecordError) as raised:
        write(_scene(), name, versions.schema, versions.loaded["v3"])
    assert raised.value.refused.refusal is versions.refused[name]
    assert _raw() == versions.stored


def test_writing_over_an_older_record_stores_the_current_version(versions: fixture.SchemaVersions) -> None:
    _store_raw(versions)
    loaded = read(_scene(), "v1", versions.schema)
    assert isinstance(loaded, Loaded)
    write(_scene(), "v1", versions.schema, loaded.record)
    assert _raw()["v1"] == {VERSION_KEY: 3, "label": "a", "count": 2, "enabled": True, "scale": 1.0}


def test_a_damaged_namespace_makes_every_record_unreadable(versions: fixture.SchemaVersions) -> None:
    _scene()[NAMESPACE] = "damaged"
    assert isinstance(read(_scene(), "v3", versions.schema), RefusedRecord)
    with pytest.raises(RefusedRecordError):
        write(_scene(), "v3", versions.schema, versions.loaded["v3"])
    assert _scene()[NAMESPACE] == "damaged"


def test_a_value_id_properties_cannot_hold_changes_nothing() -> None:
    # Blender converts the whole record before storing it, so a failed write leaves the old one.
    schema = Schema("s", version=1, record_type=Single)
    write(_scene(), "s", schema, Single(1))
    before = _raw()
    with pytest.raises(OverflowError):
        write(_scene(), "s", schema, Single(2**40))
    assert _raw() == before


def test_writing_another_record_type_is_misuse(versions: fixture.SchemaVersions) -> None:
    with pytest.raises(TypeError, match="sample: expected a Sample, not Single"):
        write(_scene(), "v3", versions.schema, Single(1))  # ty: ignore[invalid-argument-type]


def test_a_missing_record_reads_as_none(versions: fixture.SchemaVersions) -> None:
    assert read(_scene(), "v3", versions.schema) is None
    _store_raw(versions)
    assert read(_scene(), "absent", versions.schema) is None


# Writing some items of a record.


@dataclass(frozen=True)
class Keyed:
    items: dict[str, dict[str, int]]


def _rename_values(fields: dict[str, Any]) -> dict[str, Any]:
    return {"items": fields.pop("values")}


KEYED = Schema("keyed", version=2, record_type=Keyed, migrations={1: _rename_values})


def _store_keyed(stored: dict[str, Any]) -> None:
    _scene()[NAMESPACE] = {"keyed": stored}


def test_writing_items_writes_only_those() -> None:
    # "z" is stored but not in the record: a whole write would drop it, so its staying shows nothing else was written.
    _store_keyed({VERSION_KEY: 2, "items": {"a": {"n": 1}, "b": {"n": 2}, "z": {"n": 9}}})
    write_items(_scene(), "keyed", KEYED, Keyed({"a": {"n": 5}, "c": {"n": 3}}), "items", ["a", "c"], ["b"])
    assert _raw() == {"keyed": {VERSION_KEY: 2, "items": {"a": {"n": 5}, "c": {"n": 3}, "z": {"n": 9}}}}


def test_writing_items_of_an_older_or_missing_record_writes_it_whole() -> None:
    _store_keyed({VERSION_KEY: 1, "values": {"a": {"n": 1}, "z": {"n": 9}}})
    record = Keyed({"a": {"n": 5}})
    write_items(_scene(), "keyed", KEYED, record, "items", ["a"], [])
    assert _raw() == {"keyed": {VERSION_KEY: 2, "items": {"a": {"n": 5}}}}
    del _scene()[NAMESPACE]
    write_items(_scene(), "keyed", KEYED, record, "items", ["a"], [])
    assert _raw() == {"keyed": {VERSION_KEY: 2, "items": {"a": {"n": 5}}}}


def test_writing_items_never_replaces_a_newer_record() -> None:
    _store_keyed({VERSION_KEY: 3, "items": {"a": {"n": 1}}})
    before = _raw()
    with pytest.raises(RefusedRecordError):
        write_items(_scene(), "keyed", KEYED, Keyed({"a": {"n": 5}}), "items", ["a"], [])
    assert _raw() == before


@pytest.mark.parametrize(
    ("items", "error"),
    [
        # Blender refuses these only as it converts each, after the items before them.
        ({"a": {"n": 5}, "x" * 64: {"n": 1}}, KeyError),
        ({"a": {"n": 5}, "b": {"n": 2**40}}, OverflowError),
    ],
)
def test_writing_items_that_cannot_be_held_changes_nothing(
    items: dict[str, dict[str, int]], error: type[Exception]
) -> None:
    _store_keyed({VERSION_KEY: 2, "items": {"a": {"n": 1}, "b": {"n": 2}}})
    before = _raw()
    with pytest.raises(error):
        write_items(_scene(), "keyed", KEYED, Keyed(items), "items", list(items), [])
    assert _raw() == before
