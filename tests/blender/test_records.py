"""Versioned records in ID properties (lifecycle.md#schema-versions).

F-SCHEMA-VERSIONS supplies the stored records and what loading each must give. They are stored
raw, as a file written by another extension version would hold them, since the extension itself
only writes current-version records.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, make_dataclass
from typing import TYPE_CHECKING, Any

import bpy
import pytest

from fixtures import records as fixture
from proscenium.records import (
    NAMESPACE,
    VERSION_KEY,
    Loaded,
    RecordRefused,
    Refusal,
    Refused,
    Schema,
    load,
    read,
    write,
    write_items,
)
from support.blend import save_and_reopen

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

UNSUPPORTED = ["failed-migration", "newer", "invalid", "unknown-field", "no-version", "not-a-group"]


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


def _refused(schema: Schema[Any], stored: object) -> Refused:
    result = load(schema, stored)
    assert isinstance(result, Refused)
    return result


# Loading: F-SCHEMA-VERSIONS' records.


def test_generator_stores_each_version(versions: fixture.SchemaVersions) -> None:
    assert [_version(versions.stored[name]) for name in ("v1", "v2", "v3", "newer")] == [1, 2, 3, 4]
    assert versions.loaded.keys() | versions.refused.keys() == versions.stored.keys()


@pytest.mark.parametrize("name", ["v1", "v2", "v3"])
def test_older_records_migrate_on_load(versions: fixture.SchemaVersions, name: str) -> None:
    # SCHEMA-02: an older record loads at the current version, keeping its fields.
    result = load(versions.schema, versions.stored[name])
    assert result == Loaded(versions.loaded[name], _version(versions.stored[name]))


@pytest.mark.parametrize("name", UNSUPPORTED)
def test_unsupported_records_are_refused_and_left_unchanged(versions: fixture.SchemaVersions, name: str) -> None:
    # SCHEMA-03, SCHEMA-04: the refusal says why, and the stored record is untouched.
    before = copy.deepcopy(versions.stored[name])
    assert _refused(versions.schema, versions.stored[name]).refusal is versions.refused[name]
    assert versions.stored[name] == before


def test_refusal_messages_name_versions_and_problem(versions: fixture.SchemaVersions) -> None:
    def message(name: str) -> str:
        return _refused(versions.schema, versions.stored[name]).message

    assert message("newer") == "sample record version 4: newer than supported: this extension reads up to version 3"
    assert message("failed-migration") == (
        "sample record version 2: migration failed: from version 2: ValueError: count -1 is negative"
    )
    assert message("invalid") == "sample record version 3: invalid: ValueError: count 'four' is not a non-negative int"
    assert message("unknown-field").startswith("sample record version 3: invalid: TypeError:")
    assert "'tint'" in message("unknown-field")
    assert message("no-version") == f"sample record: unreadable: no {VERSION_KEY} of 1 or more"
    assert message("not-a-group") == "sample record: unreadable: stored as str, not a group"


def test_loading_never_changes_the_stored_record(versions: fixture.SchemaVersions) -> None:
    # The migrations rename and add keys in place; they get a copy.
    stored = versions.stored["v1"]
    before = copy.deepcopy(stored)
    assert isinstance(load(versions.schema, stored), Loaded)
    assert stored == before


def test_a_migration_whose_result_is_not_a_record_failed() -> None:
    schema = Schema("s", version=2, record=Single, migrations={1: lambda f: {}})
    result = _refused(schema, {VERSION_KEY: 1, "a": 1})
    assert result.refusal is Refusal.MIGRATION_FAILED
    assert "TypeError" in result.message  # the dataclass's missing field


def test_a_migration_that_raises_anything_failed() -> None:
    schema = Schema("s", version=2, record=Single, migrations={1: lambda f: f["missing"]})
    result = _refused(schema, {VERSION_KEY: 1, "a": 1})
    assert result.refusal is Refusal.MIGRATION_FAILED
    assert "KeyError" in result.message


@pytest.mark.parametrize(
    ("kwargs", "error", "match"),
    [
        ({"version": 3, "migrations": {1: lambda f: f}}, ValueError, "needs one migration from each version below 3"),
        ({"version": 1, "migrations": {0: lambda f: f}}, ValueError, "needs one migration from each version below 1"),
        ({"version": 1, "record": dict}, TypeError, "the record type must be a dataclass"),
    ],
)
def test_schema_definition_is_checked(kwargs: dict[str, Any], error: type[Exception], match: str) -> None:
    params: dict[str, Any] = {"record": Single, **kwargs}
    with pytest.raises(error, match=match):
        Schema("s", **params)


def test_the_version_key_is_reserved() -> None:
    versioned = make_dataclass("Versioned", [(VERSION_KEY, int)], frozen=True)
    with pytest.raises(ValueError, match=f"{VERSION_KEY!r} is reserved"):
        Schema("s", version=1, record=versioned)  # ty: ignore[invalid-argument-type] - made at runtime


# Storage in ID properties.


@dataclass(frozen=True)
class Pointers:
    target: bpy.types.Collection
    by_id: dict[str, bpy.types.Collection]
    items: list[dict[str, int]]


POINTERS = Schema("pointers", version=1, record=Pointers)


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
        assert isinstance(result, Refused)
        assert result.refusal is refusal
    assert _raw() == versions.stored
    assert not bpy.data.is_dirty


@pytest.mark.parametrize("name", ["newer", "no-version", "not-a-group"])
def test_writing_never_replaces_a_newer_or_unreadable_record(versions: fixture.SchemaVersions, name: str) -> None:
    # SCHEMA-03, SCHEMA-04: what the stored version shows is refused without loading the record.
    _store_raw(versions)
    with pytest.raises(RecordRefused) as raised:
        write(_scene(), name, versions.schema, versions.loaded["v3"])
    assert raised.value.refused.refusal is versions.refused[name]
    assert _raw() == versions.stored


@pytest.mark.parametrize("name", ["failed-migration", "invalid", "unknown-field"])
def test_writing_relies_on_its_caller_to_have_read_a_supported_version(
    versions: fixture.SchemaVersions, name: str
) -> None:
    # A damaged or failing record at a supported version takes loading to see. Writers read first and refuse
    # on a refusal, which load gives here, so writing doesn't load it again.
    _store_raw(versions)
    assert isinstance(load(versions.schema, versions.stored[name]), Refused)
    write(_scene(), name, versions.schema, versions.loaded["v3"])
    assert read(_scene(), name, versions.schema) == Loaded(versions.loaded["v3"], 3)


def test_writing_over_an_older_record_stores_the_current_version(versions: fixture.SchemaVersions) -> None:
    _store_raw(versions)
    loaded = read(_scene(), "v1", versions.schema)
    assert isinstance(loaded, Loaded)
    write(_scene(), "v1", versions.schema, loaded.record)
    assert _raw()["v1"] == {VERSION_KEY: 3, "label": "a", "count": 2, "enabled": True, "scale": 1.0}


def test_a_damaged_namespace_makes_every_record_unreadable(versions: fixture.SchemaVersions) -> None:
    _scene()[NAMESPACE] = "damaged"
    assert isinstance(read(_scene(), "v3", versions.schema), Refused)
    with pytest.raises(RecordRefused):
        write(_scene(), "v3", versions.schema, versions.loaded["v3"])
    assert _scene()[NAMESPACE] == "damaged"


def test_a_value_id_properties_cannot_hold_changes_nothing() -> None:
    # Blender converts the whole record before storing it, so a failed write leaves the old one.
    schema = Schema("s", version=1, record=Single)
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


KEYED = Schema("keyed", version=2, record=Keyed, migrations={1: _rename_values})


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
    with pytest.raises(RecordRefused):
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
