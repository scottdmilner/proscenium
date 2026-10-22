"""F-SCHEMA-VERSIONS: stored records at every version the record framework must handle (lifecycle.md#schema-versions).

SAMPLE is a test schema at version 3 with two migrations, standing in for the real schemas until
they have older versions of their own:

- version 1: label, size;
- version 2: size renamed count, and enabled added (true for every version 1 record);
- version 3: scale added (1.0). Version 3 counts are never negative, and a negative version 2
  count has no version 3 meaning, so that migration rejects it.

The generator yields each stored record as ID properties hold it, with what loading it must give,
derived from the migrations above. It also yields binding configurations (proscenium.persistence.binding_records) a
newer extension or damage could leave; binding configuration has no older version yet. M5 adds
pending-cleanup records once it defines their schema.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from proscenium.persistence.records import VERSION_KEY, RefusalReason, Schema

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@dataclass(frozen=True)
class Sample:
    """A version 3 sample record."""

    label: str
    count: int
    enabled: bool
    scale: float

    def __post_init__(self) -> None:
        # A check of the kind a real record makes where a hand-edited value would mislead.
        if type(self.count) is not int or self.count < 0:
            raise ValueError(f"count {self.count!r} is not a non-negative int")


def _v1_to_v2(fields: dict[str, Any]) -> dict[str, Any]:
    fields["count"] = fields.pop("size")
    fields["enabled"] = True
    return fields


def _v2_to_v3(fields: dict[str, Any]) -> dict[str, Any]:
    if fields["count"] < 0:
        raise ValueError(f"count {fields['count']} is negative")
    return fields | {"scale": 1.0}


SAMPLE = Schema(name="sample", version=3, record_type=Sample, migrations={1: _v1_to_v2, 2: _v2_to_v3})


@dataclass(frozen=True)
class SchemaVersions:
    schema: Schema[Sample]
    stored: dict[str, object]  # record name -> the record as stored
    loaded: dict[str, Sample]  # the records that load -> each at version 3
    refused: dict[str, RefusalReason]  # the records that don't -> why
    bindings: dict[str, object]  # binding configurations that can't be read, as stored
    bindings_refused: dict[str, RefusalReason]  # each -> why


@contextmanager
def schema_versions(_dest: Path) -> Generator[SchemaVersions]:
    """F-SCHEMA-VERSIONS: sample records that migrate, fail, are newer, damaged, or not records at all.

    The records are values, not files: tests store them in ID properties or load them directly.
    """
    current = {"label": "c", "count": 4, "enabled": False, "scale": 2.5}
    # A valid version 1 file-source configuration whose destination was removed (a cleared pointer).
    binding = {
        "source_kind": "file",
        "path": "//shot.usda",
        "source_key": None,
        "root_layer_identifier": None,
        "destination": None,
        "payload_policy": "load_all",
    }
    yield SchemaVersions(
        schema=SAMPLE,
        stored={
            "v1": {VERSION_KEY: 1, "label": "a", "size": 2},
            "v2": {VERSION_KEY: 2, "label": "b", "count": 3, "enabled": False},
            "v3": {VERSION_KEY: 3, **current},
            "failed-migration": {VERSION_KEY: 2, "label": "d", "count": -1, "enabled": True},
            "newer": {VERSION_KEY: 4, **current, "tint": "red"},
            "invalid": {VERSION_KEY: 3, **current, "count": "four"},
            "unknown-field": {VERSION_KEY: 3, **current, "tint": "red"},
            "no-version": {"label": "e", "count": 5},
            "not-a-group": "damaged",
        },
        loaded={
            "v1": Sample(label="a", count=2, enabled=True, scale=1.0),
            "v2": Sample(label="b", count=3, enabled=False, scale=1.0),
            "v3": Sample(**current),
        },
        refused={
            "failed-migration": RefusalReason.MIGRATION_FAILED,
            "newer": RefusalReason.NEWER,
            "invalid": RefusalReason.INVALID,
            "unknown-field": RefusalReason.INVALID,
            "no-version": RefusalReason.UNREADABLE,
            "not-a-group": RefusalReason.UNREADABLE,
        },
        bindings={
            "newer": {VERSION_KEY: 2, **binding, "units": 0.01},
            "no-path": {VERSION_KEY: 1, **binding, "path": None},
            "unknown-policy": {VERSION_KEY: 1, **binding, "payload_policy": "load_some"},
            # Version 1 under the field names it had before source_kind and source_key: never released, so refused.
            "old-field-names": {
                VERSION_KEY: 1,
                **{k: v for k, v in binding.items() if k not in ("source_kind", "source_key")},
                "source": "file",
                "key": None,
            },
        },
        bindings_refused={
            "newer": RefusalReason.NEWER,
            "no-path": RefusalReason.INVALID,
            "unknown-policy": RefusalReason.INVALID,
            "old-field-names": RefusalReason.INVALID,
        },
    )
