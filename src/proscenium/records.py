"""Versioned records in Blender ID properties (lifecycle.md#schema-versions).

A record is a nested ID-property group with a version under VERSION_KEY. Each ID that carries records holds
them in one group, id_["proscenium"], one record per key. A schema names the dataclass a record
loads as, and the migration from each older version to the next. A record's fields may hold
dataclasses, in groups and lists too: writing stores them as groups, and the record's
__post_init__ builds them again on load.

Reading never writes: an older record migrates in memory and is stored at the current version
only when the extension next writes it. A record that can't be read is a Refused value, never an
exception, so its binding can keep its display and report why. Writers read a record before
writing it and refuse on any refusal, so a newer, damaged, or failed record survives until the user
repairs it; writing itself refuses to replace one that is unreadable or newer.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import bpy
    from _typeshed import DataclassInstance

NAMESPACE = "proscenium"
VERSION_KEY = "_schema_version"

type Migration = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class Schema[R: DataclassInstance]:
    kind: str  # names the record in messages, e.g. "binding"
    version: int  # the current version
    record: type[R]  # the dataclass a current-version record loads as; it may check its fields
    migrations: Mapping[int, Migration] = dataclasses.field(default_factory=dict)  # n -> n + 1, on plain values

    def __post_init__(self) -> None:
        if not dataclasses.is_dataclass(self.record):
            raise TypeError(f"{self.kind}: the record type must be a dataclass")
        if set(self.migrations) != set(range(1, self.version)):
            raise ValueError(f"{self.kind}: needs one migration from each version below {self.version}")
        if VERSION_KEY in {f.name for f in dataclasses.fields(self.record)}:
            raise ValueError(f"{self.kind}: {VERSION_KEY!r} is reserved")


class Refusal(StrEnum):
    NEWER = "newer than supported"
    MIGRATION_FAILED = "migration failed"
    INVALID = "invalid"  # at the current version, but its fields don't make a record
    UNREADABLE = "unreadable"  # not a group, or no version


@dataclass(frozen=True, slots=True)
class Loaded[R]:
    record: R
    stored_version: int


@dataclass(frozen=True, slots=True)
class Refused:
    kind: str
    stored_version: int | None  # None when the record has no readable version
    refusal: Refusal
    message: str  # names the record, the versions, and the problem


class RecordRefused(Exception):  # noqa: N818 (named for the Refused value it carries)
    """Writing would replace a stored record the extension can't read."""

    refused: Refused

    def __init__(self, refused: Refused) -> None:
        super().__init__(refused.message)
        self.refused = refused


def load[R: DataclassInstance](schema: Schema[R], stored: object) -> Loaded[R] | Refused:
    """The stored record, as plain values, loaded at the schema's current version, or why it can't be.

    stored is left unchanged: migrations run on a copy.
    """
    return _load(schema, stored, copy=True)


def _load[R: DataclassInstance](schema: Schema[R], stored: object, *, copy: bool) -> Loaded[R] | Refused:
    version = _version(schema, stored)
    if isinstance(version, Refused):
        return version
    assert isinstance(stored, Mapping)
    fields = {key: value for key, value in stored.items() if key != VERSION_KEY}
    if copy:
        fields = _copy(fields)
    # Any exception is a refusal: stored data must never crash the extension. A missing or unknown
    # field is the dataclass's TypeError.
    for step in range(version, schema.version):
        try:
            fields = schema.migrations[step](fields)
        except Exception as exc:  # noqa: BLE001
            return _refuse(
                schema, Refusal.MIGRATION_FAILED, version, f"from version {step}: {type(exc).__name__}: {exc}"
            )
    try:
        record = schema.record(**fields)
    except Exception as exc:  # noqa: BLE001
        refusal = Refusal.INVALID if version == schema.version else Refusal.MIGRATION_FAILED
        return _refuse(schema, refusal, version, f"{type(exc).__name__}: {exc}")
    return Loaded(record, version)


def _version(schema: Schema[Any], stored: object) -> int | Refused:
    """The stored record's version, or why it's unreadable or newer than supported.

    stored is a plain group or a stored ID-property group, so a write can check one without copying it.
    """
    if not isinstance(stored, Mapping) and not hasattr(stored, "to_dict"):
        return _refuse(schema, Refusal.UNREADABLE, None, f"stored as {type(stored).__name__}, not a group")
    version = stored.get(VERSION_KEY)  # ty: ignore[unresolved-attribute] - a Mapping or an IDPropertyGroup
    if type(version) is not int or version < 1:
        return _refuse(schema, Refusal.UNREADABLE, None, f"no {VERSION_KEY} of 1 or more")
    if version > schema.version:
        return _refuse(schema, Refusal.NEWER, version, f"this extension reads up to version {schema.version}")
    return version


def _refuse(schema: Schema[Any], refusal: Refusal, version: int | None, detail: str) -> Refused:
    at = "" if version is None else f" version {version}"
    return Refused(schema.kind, version, refusal, f"{schema.kind} record{at}: {refusal}: {detail}")


def stored(id_: bpy.types.ID, key: str) -> object | None:
    """A copy of the stored record under key, as plain values; None if there is none."""
    namespace = id_.get(NAMESPACE)
    if namespace is None:
        return None
    if not hasattr(namespace, "to_dict"):  # the namespace itself is damaged: its records are unreadable
        return _plain(namespace)
    return _plain(namespace.get(key))


def keys(id_: bpy.types.ID) -> list[str]:
    """The keys of id_'s records; none if its namespace is missing or damaged."""
    namespace = id_.get(NAMESPACE)
    return list(namespace.keys()) if hasattr(namespace, "to_dict") else []


def read[R: DataclassInstance](id_: bpy.types.ID, key: str, schema: Schema[R]) -> Loaded[R] | Refused | None:
    """The record under key at the schema's current version, why it can't be read, or None if there is none."""
    value = stored(id_, key)  # already a copy, which the migrations may change
    return None if value is None else _load(schema, value, copy=False)


def write[R: DataclassInstance](id_: bpy.types.ID, key: str, schema: Schema[R], record: R) -> None:
    """Store record under key at the current version.

    Raises RecordRefused, changing nothing, if the stored record is unreadable (not a group, or no
    version) or newer than supported: what can be told without loading it. A record at a supported
    version that fails to load, damaged or failing migration, isn't caught here. Every writer reads
    the record first and refuses on any refusal, so loading it again on each write would only cost
    time. A value ID properties can't hold raises Blender's own error, which also changes nothing.
    """
    if type(record) is not schema.record:
        raise TypeError(f"{schema.kind}: expected a {schema.record.__name__}, not {type(record).__name__}")
    namespace = id_.get(NAMESPACE)
    if namespace is not None and not hasattr(namespace, "to_dict"):
        raise RecordRefused(Refused(schema.kind, None, Refusal.UNREADABLE, f"{NAMESPACE} is not a group"))
    existing = None if namespace is None else namespace.get(key)
    if existing is not None and isinstance(result := _version(schema, existing), Refused):
        raise RecordRefused(result)
    value = {VERSION_KEY: schema.version} | _unstructure(record)
    if namespace is None:
        id_[NAMESPACE] = {}
        namespace = id_[NAMESPACE]
    namespace[key] = value


def _unstructure(value: Any) -> Any:
    """value as ID properties hold it: dataclasses, nested in groups and lists too, as dicts of their fields.

    Tuples become lists. Not dataclasses.asdict, which deep-copies the other values, ID pointers included.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _unstructure(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {key: _unstructure(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_unstructure(item) for item in value]
    return value


def _copy(value: Any) -> Any:
    """A copy of the groups and lists in value, for migrations to change; ID pointers are shared."""
    if isinstance(value, Mapping):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


def _plain(value: Any) -> Any:
    """ID-property groups and arrays as dicts and lists; ID pointers and scalars as they are."""
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "to_list"):
        return value.to_list()
    return value
