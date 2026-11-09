"""Sampled time codes: the time codes a time-varying fixture is evaluated at (acceptance.md#sampled-time-codes).

A fixture declares how it varies in a TimeVariation, from how it is built (ATIME-02), and sampled gives its time codes
by kind (ATIME-01): the stage's start and end, an interior non-integer one, its selected authored samples (all, or 8
spread evenly, ATIME-03), each transition and the time codes just around it, the midpoints between consecutive
relevant time codes, one before the start and one after the end, the default time code, and 2 seeded from its fixture
ID. A production-scale fixture gets neither authored nor seeded samples. Every offset is a binary fraction, so every
time code is exactly representable as a float. Time codes are floats, or None for the default time code, as the
fixtures give them.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

AUTHORED = 8  # a bespoke fixture's selected authored samples when it has more
SEEDED = 2  # its seeded samples
AROUND = 0.5  # the offset of the time codes around a transition
OUTSIDE = 1.0  # how far before the start and after the end
INTERIOR = 0.375  # the interior non-integer time code's offset past the integer at or below the range's middle
FRACTION = 64  # seeded time codes are multiples of 1/64


@dataclass(frozen=True)
class TimeVariation:
    """How a time-varying fixture varies, from how it is built (acceptance.md#sampled-time-codes, ATIME-02)."""

    start: float  # the stage's startTimeCode
    end: float  # its endTimeCode
    samples: tuple[float, ...]  # every authored sample time
    transitions: tuple[float, ...]  # time codes where topology or visibility changes


@dataclass(frozen=True)
class SampledTimeCodes:
    """A fixture's sampled time codes, by kind; time_codes gives them all."""

    start: float
    end: float
    interior: float  # strictly between start and end, not an integer
    authored: tuple[float, ...]  # the selected authored sample times
    transitions: tuple[float, ...]  # each transition, and the time codes just before and after it
    midpoints: tuple[float, ...]  # between consecutive start, end, authored samples, and transitions
    before: float
    after: float
    seeded: tuple[float, ...]

    @property
    def time_codes(self) -> tuple[float | None, ...]:
        """Every sampled time code once, the default time code first, then in increasing order."""
        floats = {self.start, self.end, self.interior, self.before, self.after}
        floats.update(self.authored, self.transitions, self.midpoints, self.seeded)
        return (None, *sorted(floats))


def sampled(fixture_id: str, variation: TimeVariation, *, production_scale: bool = False) -> SampledTimeCodes:
    """fixture_id's sampled time codes; seeded from fixture_id, so the same in every run and process."""
    start, end = variation.start, variation.end
    if not end - start >= 2:  # so the interior time code is strictly inside
        raise ValueError(f"{fixture_id}: its time range [{start}, {end}] holds no interior non-integer time code")
    authored = () if production_scale else _spread(variation.samples)
    transitions = tuple(sorted({t + d for t in variation.transitions for d in (-AROUND, 0.0, AROUND)}))
    relevant = sorted({start, end, *authored, *variation.transitions})
    rng = random.Random(fixture_id)  # a str seed hashes the same in every process, unlike hash()
    seeded = () if production_scale else tuple(_seeded(rng, start, end) for _ in range(SEEDED))
    return SampledTimeCodes(
        start=start,
        end=end,
        interior=math.floor((start + end) / 2) + INTERIOR,
        authored=authored,
        transitions=transitions,
        midpoints=tuple((a + b) / 2 for a, b in zip(relevant, relevant[1:], strict=False)),
        before=start - OUTSIDE,
        after=end + OUTSIDE,
        seeded=seeded,
    )


def _spread(samples: tuple[float, ...]) -> tuple[float, ...]:
    """All of samples, or AUTHORED of them spread evenly, the first and last included."""
    if len(samples) <= AUTHORED:
        return samples
    last = len(samples) - 1
    return tuple(samples[round(i * last / (AUTHORED - 1))] for i in range(AUTHORED))


def _seeded(rng: random.Random, start: float, end: float) -> float:
    """A time code in [start, end], a multiple of 1 / FRACTION."""
    return rng.randint(round(start * FRACTION), round(end * FRACTION)) / FRACTION
