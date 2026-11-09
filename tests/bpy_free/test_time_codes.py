"""The sampled-time-codes helper (support/time_codes.py) gives each kind acceptance.md's Sampled Time Codes lists.

ATIME-01 on the time-varying fixtures, F-TRANSFORMS and F-VISIBILITY-PURPOSE, whose TimeVariation
test_evaluation_fixtures.py checks against the authored samples (ATIME-02); ATIME-03's counts on those and on
variations made here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import astuple
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pxr import Usd

from fixtures import evaluation
from support import time_codes
from support.time_codes import TimeVariation

if TYPE_CHECKING:
    from collections.abc import Callable

TESTS = Path(__file__).resolve().parents[1]
MANY = TimeVariation(start=0.0, end=40.0, samples=tuple(float(t) for t in range(0, 41, 2)), transitions=(13.0,))


def _transforms(tmp_path: Path) -> TimeVariation:
    with evaluation.transforms(tmp_path) as scene:
        return scene.variation


def _visibility(tmp_path: Path) -> TimeVariation:
    with evaluation.visibility_purpose(tmp_path) as scene:
        return scene.variation


VARYING: dict[str, Callable[[Path], TimeVariation]] = {"F-TRANSFORMS": _transforms, "F-VISIBILITY-PURPOSE": _visibility}


@pytest.mark.parametrize("fixture_id", VARYING)
def test_each_kind_of_time_code(fixture_id: str, tmp_path: Path) -> None:
    # ATIME-01: start and end, an interior non-integer, the authored samples, each transition and just around it, the
    # midpoints, before and after, the default, and the seeded ones, each exactly representable.
    variation = VARYING[fixture_id](tmp_path)
    sampled = time_codes.sampled(fixture_id, variation)
    assert (sampled.start, sampled.end) == (variation.start, variation.end)
    assert variation.start < sampled.interior < variation.end and not sampled.interior.is_integer()
    assert sampled.authored == variation.samples  # no more than 8 (ATIME-03)
    for transition in variation.transitions:
        assert {transition - 0.5, transition, transition + 0.5} <= set(sampled.transitions)
    relevant = sorted({variation.start, variation.end, *variation.samples, *variation.transitions})
    assert sampled.midpoints == tuple((a + b) / 2 for a, b in zip(relevant, relevant[1:], strict=False))
    assert sampled.before < variation.start and sampled.after > variation.end
    assert len(sampled.seeded) == 2 and all(variation.start <= t <= variation.end for t in sampled.seeded)
    every = sampled.time_codes
    assert every[0] is None and len(set(every)) == len(every)
    for time_code in every[1:]:
        assert time_code is not None
        assert Fraction(time_code).denominator <= time_codes.FRACTION, time_code  # a short binary fraction
        assert Usd.TimeCode(time_code).GetValue() == time_code


def test_seeds_come_from_the_fixture_id() -> None:
    # ATIME-02: the same ID seeds the same samples, here and in a process with another hash seed; another ID others.
    seeded = time_codes.sampled("F-TRANSFORMS", MANY).seeded
    assert time_codes.sampled("F-TRANSFORMS", MANY).seeded == seeded
    assert time_codes.sampled("F-VISIBILITY-PURPOSE", MANY).seeded != seeded
    script = (
        "import json; from support import time_codes; from support.time_codes import TimeVariation; "
        f"print(json.dumps(time_codes.sampled('F-TRANSFORMS', TimeVariation(*{astuple(MANY)!r})).seeded))"
    )
    env = {**os.environ, "PYTHONHASHSEED": "12345", "PYTHONPATH": os.pathsep.join([str(TESTS), *sys.path])}
    printed = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True)
    assert tuple(json.loads(printed.stdout)) == seeded


def test_many_authored_samples_are_spread_evenly() -> None:
    # ATIME-03: with more than 8 authored samples, 8 spread evenly, the first and last included, and 2 seeded.
    sampled = time_codes.sampled("F-MANY", MANY)
    assert len(sampled.authored) == 8 and set(sampled.authored) <= set(MANY.samples)
    assert (sampled.authored[0], sampled.authored[-1]) == (MANY.samples[0], MANY.samples[-1])
    gaps = [b - a for a, b in zip(sampled.authored, sampled.authored[1:], strict=False)]
    assert max(gaps) - min(gaps) <= 2.0  # one sample interval
    assert len(sampled.seeded) == 2


def test_a_production_scale_fixture_gets_only_the_other_kinds() -> None:
    # ATIME-03: no authored or seeded samples; its time codes are exactly the other kinds'.
    sampled = time_codes.sampled("F-MANY", MANY, production_scale=True)
    assert (sampled.authored, sampled.seeded) == ((), ())
    others = {sampled.start, sampled.end, sampled.interior, sampled.before, sampled.after}
    others |= {*sampled.transitions, *sampled.midpoints}
    assert sampled.time_codes == (None, *sorted(others))
    assert sampled.midpoints == (6.5, 26.5)  # between start, the transition, and end alone
