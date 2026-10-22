"""A binding's published generation and last attempt (lifecycle.md#binding-state).

The published generation is what the display was produced with: the generation record and the
ownership manifest beside it on the destination collection (proscenium.persistence.manifests), and the
correspondence M7 adds. It describes the destination's content, so it travels with the destination
on copy routes, as the manifest does.

The last attempt is the most recent synchronization attempt and its result. It is on the target
scene beside the binding's configuration, under its own key: it exists without a destination or a
publication, and reading the configuration doesn't load its diagnostics.

Nothing writes these records before M5's synchronization transaction, so M5 can still refine their
version 1 fields. Time codes are stored as their value, or None for the USD default time code,
whose value is NaN, which would break equality.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pxr import Usd

from ..core.results import Diagnostic, ResultState
from ..core.source_access import PayloadPolicy
from . import records
from .records import Schema

if TYPE_CHECKING:
    import bpy

    from .records import Loaded, RefusedRecord

GENERATION_KEY = "generation"
ATTEMPT_PREFIX = "attempt."


def stored_time(time_code: Usd.TimeCode) -> float | None:
    return None if time_code.IsDefault() else time_code.GetValue()


def time_code(stored: float | None) -> Usd.TimeCode:
    return Usd.TimeCode.Default() if stored is None else Usd.TimeCode(stored)


def _settle(record: Any) -> None:
    """Turn a stored record's plain values back into the fields' types; ValueError or TypeError if they can't be."""
    object.__setattr__(record, "payload_policy", PayloadPolicy(record.payload_policy))
    if not isinstance(record.time_code, float | None):
        raise TypeError("a time code is a float, or None for the default time code")
    diagnostics = tuple(d if isinstance(d, Diagnostic) else Diagnostic(**d) for d in record.diagnostics)
    object.__setattr__(record, "diagnostics", diagnostics)


@dataclass(frozen=True, slots=True)
class Generation:
    """What a binding's published display was produced with."""

    binding_id: str
    payload_policy: PayloadPolicy
    time_code: float | None  # see stored_time
    diagnostics: tuple[Diagnostic, ...]  # its source/display diagnostics

    def __post_init__(self) -> None:
        _settle(self)
        if type(self.binding_id) is not str:
            raise TypeError("a generation names its binding")


@dataclass(frozen=True, slots=True)
class LastAttempt:
    """The most recent synchronization attempt: what it asked for, and how it ended."""

    payload_policy: PayloadPolicy
    time_code: float | None  # see stored_time
    result: ResultState
    diagnostics: tuple[Diagnostic, ...]

    def __post_init__(self) -> None:
        _settle(self)
        object.__setattr__(self, "result", ResultState(self.result))


GENERATION = Schema("generation", version=1, record_type=Generation)
ATTEMPT = Schema("last attempt", version=1, record_type=LastAttempt)


def read_generation(destination: bpy.types.Collection) -> Loaded[Generation] | RefusedRecord | None:
    return records.read(destination, GENERATION_KEY, GENERATION)


def write_generation(destination: bpy.types.Collection, generation: Generation) -> None:
    """Raises RefusedRecordError, changing nothing, over a stored generation that can't be read."""
    records.write(destination, GENERATION_KEY, GENERATION, generation)


def read_last_attempt(scene: bpy.types.Scene, binding_id: str) -> Loaded[LastAttempt] | RefusedRecord | None:
    return records.read(scene, ATTEMPT_PREFIX + binding_id, ATTEMPT)


def write_last_attempt(scene: bpy.types.Scene, binding_id: str, attempt: LastAttempt) -> None:
    """Raises RefusedRecordError, changing nothing, over a stored last attempt that can't be read."""
    records.write(scene, ATTEMPT_PREFIX + binding_id, ATTEMPT, attempt)
