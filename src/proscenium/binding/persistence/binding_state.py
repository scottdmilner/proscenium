"""A binding's published generation and last attempt (lifecycle.md#binding-state).

The published generation is what the display was produced with: the generation record and the
ownership manifest beside it on the destination collection (proscenium.binding.persistence.manifests), and the
correspondence M7 adds. The generation record holds the time code it was synchronized at and those M5's cache
added to it since (pipeline.md#cached-time-codes), and the source revision it was synchronized from, which cache
compares with the binding's current one; it's stored, so undo restores it with the generation it describes. It
describes the destination's content, so it travels with the destination on copy routes, as the manifest does.

The last attempt is the most recent synchronization attempt and its result. It is on the destination beside the
binding's configuration and the generation, under its own key: it exists without a publication, and reading the
configuration doesn't load its diagnostics.

The synchronization transaction writes both (proscenium.synchronization): the generation as part of publication,
and the last attempt at every attempt's end.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pxr import Usd

from .. import results
from ..source_access import stages
from . import records
from .records import Schema

if TYPE_CHECKING:
    import bpy

    from ..source_access import identifiers
    from .records import Loaded, RefusedRecord

GENERATION_KEY = "generation"
ATTEMPT_KEY = "attempt"


def stored_time(time_code: Usd.TimeCode) -> float | None:
    """A time code as a record stores it: its value, or None for the default time code, whose NaN breaks equality."""
    return None if time_code.IsDefault() else time_code.GetValue()


def time_code(stored: float | None) -> Usd.TimeCode:
    """A stored time code as a Usd.TimeCode again."""
    return Usd.TimeCode.Default() if stored is None else Usd.TimeCode(stored)


def _settle(record: Any) -> None:
    """Turn a stored record's plain values back into the fields' types; ValueError or TypeError if they can't be."""
    object.__setattr__(record, "payload_policy", stages.PayloadPolicy(record.payload_policy))
    if not isinstance(record.time_code, float | None):
        raise TypeError("a time code is a float, or None for the default time code")
    diagnostics = tuple(d if isinstance(d, results.Diagnostic) else results.Diagnostic(**d) for d in record.diagnostics)
    object.__setattr__(record, "diagnostics", diagnostics)


@dataclass(frozen=True, slots=True)
class Generation:
    """What a binding's published display was produced with."""

    binding_id: identifiers.BindingId
    payload_policy: stages.PayloadPolicy
    time_code: float | None  # see stored_time
    source_revision: stages.SourceRevision  # BindingStages.source_revision when it was synchronized
    diagnostics: tuple[results.Diagnostic, ...]  # its source/display diagnostics
    # The time codes cached in it since, sorted, without its own; one at the default time code has none to cache.
    cached_time_codes: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _settle(self)
        if type(self.binding_id) is not str:
            raise TypeError("a generation names its binding")
        if type(self.source_revision) is not str:
            raise TypeError("a source revision is a string")
        if not self.source_revision:
            raise ValueError("a generation names the source revision it was synchronized from")
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

    payload_policy: stages.PayloadPolicy
    time_code: float | None  # see stored_time
    diagnostics: tuple[results.Diagnostic, ...]

    def __post_init__(self) -> None:
        _settle(self)

    @property
    def result(self) -> results.ResultState:
        """How it ended, from its diagnostics."""
        return results.result_state(self.diagnostics)


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


def remove_generation(destination: bpy.types.Collection) -> None:
    """Remove the destination's published generation, if it has one; raises as write_generation does."""
    records.remove(destination, GENERATION_KEY, GENERATION)


def read_last_attempt(destination: bpy.types.Collection) -> Loaded[LastAttempt] | RefusedRecord | None:
    """The binding's last attempt on its destination, why it can't be read, or None if it has none."""
    return records.read(destination, ATTEMPT_KEY, ATTEMPT)


def write_last_attempt(destination: bpy.types.Collection, attempt: LastAttempt) -> None:
    """Store the binding's last attempt on its destination.

    Raises RefusedRecordError, changing nothing, over a stored last attempt that can't be read.
    """
    records.write(destination, ATTEMPT_KEY, ATTEMPT, attempt)
