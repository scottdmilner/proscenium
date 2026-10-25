"""Loading versioned records: migration and refusal (lifecycle.md#schema-versions).

F-SCHEMA-VERSIONS supplies the stored records, as values, and what loading each must give. Storing
them in ID properties is tested in tests/blender/test_records.py.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, make_dataclass
from typing import TYPE_CHECKING, Any

import pytest

from fixtures import records as fixture
from proscenium.persistence.records import VERSION_KEY, Loaded, RefusalReason, RefusedRecord, Schema, load

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


def _version(stored: object) -> int:
    assert isinstance(stored, dict)
    return stored[VERSION_KEY]


def _refused(schema: Schema[Any], stored: object) -> RefusedRecord:
    result = load(schema, stored)
    assert isinstance(result, RefusedRecord)
    return result


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
    # SCHEMA-03: the refusal reports why: the record, its stored version, and the problem.
    def message(name: str) -> str:
        return _refused(versions.schema, versions.stored[name]).message

    expected = {
        "newer": ["sample record", "4", "newer", "3"],  # and the version this extension reads up to
        "failed-migration": ["sample record", "2", "migration", "ValueError", "count -1"],
        "invalid": ["sample record", "3", "invalid", "ValueError", "'four'"],
        "unknown-field": ["sample record", "3", "invalid", "TypeError", "'tint'"],
        "no-version": ["sample record", "unreadable", VERSION_KEY],
        "not-a-group": ["sample record", "unreadable", "str"],
    }
    for name, parts in expected.items():
        assert all(part in message(name) for part in parts), (name, message(name))


def test_loading_never_changes_the_stored_record(versions: fixture.SchemaVersions) -> None:
    # The migrations rename and add keys in place; they get a copy.
    stored = versions.stored["v1"]
    before = copy.deepcopy(stored)
    assert isinstance(load(versions.schema, stored), Loaded)
    assert stored == before


def test_a_migration_whose_result_is_not_a_record_failed() -> None:
    schema = Schema("s", version=2, record_type=Single, migrations={1: lambda f: {}})
    result = _refused(schema, {VERSION_KEY: 1, "a": 1})
    assert result.refusal is RefusalReason.MIGRATION_FAILED
    assert "TypeError" in result.message  # the dataclass's missing field


def test_a_migration_that_raises_anything_failed() -> None:
    schema = Schema("s", version=2, record_type=Single, migrations={1: lambda f: f["missing"]})
    result = _refused(schema, {VERSION_KEY: 1, "a": 1})
    assert result.refusal is RefusalReason.MIGRATION_FAILED
    assert "KeyError" in result.message


@pytest.mark.parametrize(
    ("kwargs", "error", "match"),
    [
        ({"version": 3, "migrations": {1: lambda f: f}}, ValueError, "needs one migration from each version below 3"),
        ({"version": 1, "migrations": {0: lambda f: f}}, ValueError, "needs one migration from each version below 1"),
        ({"version": 1, "record_type": dict}, TypeError, "the record type must be a dataclass"),
    ],
)
def test_schema_definition_is_checked(kwargs: dict[str, Any], error: type[Exception], match: str) -> None:
    params: dict[str, Any] = {"record_type": Single, **kwargs}
    with pytest.raises(error, match=match):
        Schema("s", **params)


def test_the_version_key_is_reserved() -> None:
    versioned = make_dataclass("Versioned", [(VERSION_KEY, int)], frozen=True)
    with pytest.raises(ValueError, match=f"{VERSION_KEY!r} is reserved"):
        Schema("s", version=1, record_type=versioned)  # ty: ignore[invalid-argument-type] - made at runtime
