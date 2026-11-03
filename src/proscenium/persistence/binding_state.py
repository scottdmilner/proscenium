"""A binding's published generation and last attempt (lifecycle.md#binding-state).

The published generation is what the display was produced with: the generation record and the
ownership manifest beside it on the destination collection (proscenium.persistence.manifests), and the
correspondence M7 adds. The generation record holds the time code it was synchronized at and those M5's cache
added to it since (pipeline.md#cached-time-codes). It describes the destination's content, so it travels with the
destination on copy routes, as the manifest does.

The last attempt is the most recent synchronization attempt and its result. It is on the target
scene beside the binding's configuration, under its own key: it exists without a destination or a
publication, and reading the configuration doesn't load its diagnostics.

Nothing writes these records before M5's synchronization transaction, so M5 can still refine their
version 1 fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pxr import Usd

from ..results import Diagnostic, ResultState
from ..source_access import PayloadPolicy
from . import records
from .records import Schema

if TYPE_CHECKING:
    import bpy

    from ..source_access.binding_ids import BindingId
    from .records import Loaded, RefusedRecord

GENERATION_KEY = "generation"
ATTEMPT_PREFIX = "attempt."


def stored_time(time_code: Usd.TimeCode) -> float | None:
    """A time code as a record stores it: its value, or None for the default time code, whose NaN breaks equality."""
    return None if time_code.IsDefault() else time_code.GetValue()


def time_code(stored: float | None) -> Usd.TimeCode:
    """A stored time code as a Usd.TimeCode again."""
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

    binding_id: BindingId
    payload_policy: PayloadPolicy
    time_code: float | None  # see stored_time
    diagnostics: tuple[Diagnostic, ...]  # its source/display diagnostics
    # The time codes cached in it since, sorted, without its own; one at the default time code has none to cache.
    cached_time_codes: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _settle(self)
        if type(self.binding_id) is not str:
            raise TypeError("a generation names its binding")
        cached = tuple(self.cached_time_codes)  # a stored one comes back as an ID-property array
        if not all(type(t) is float for t in cached):
            raise TypeError("a cached time code is a float")
        if list(cached) != sorted(set(cached)):
            raise ValueError("cached time codes are sorted, each once")
        if self.time_code in cached:
            raise ValueError("a generation's own time code isn't one cached in it")
        if cached and self.time_code is None:
            raise ValueError("a generation synchronized at the default time code has no time codes to cache")
        object.__setattr__(self, "cached_time_codes", cached)


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
    """The destination's published generation, why it can't be read, or None if it has none."""
    return records.read(destination, GENERATION_KEY, GENERATION)


def write_generation(destination: bpy.types.Collection, generation: Generation) -> None:
    """Store the destination's published generation.

    Raises RefusedRecordError, changing nothing, over a stored generation that can't be read.
    """
    records.write(destination, GENERATION_KEY, GENERATION, generation)


def read_last_attempt(scene: bpy.types.Scene, binding_id: BindingId) -> Loaded[LastAttempt] | RefusedRecord | None:
    """The binding's last attempt on scene, why it can't be read, or None if it has none."""
    return records.read(scene, ATTEMPT_PREFIX + binding_id, ATTEMPT)


def write_last_attempt(scene: bpy.types.Scene, binding_id: BindingId, attempt: LastAttempt) -> None:
    """Store the binding's last attempt on scene.

    Raises RefusedRecordError, changing nothing, over a stored last attempt that can't be read.
    """
    records.write(scene, ATTEMPT_PREFIX + binding_id, ATTEMPT, attempt)
