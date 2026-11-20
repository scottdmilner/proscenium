"""F-TIME-VARIATIONS: each way M7's content varies over time, for cached time codes (pipeline.md#cached-time-codes).

time_variations copies Scene.TIME_VARIATIONS, opens time_variations.usda as the caller's live stage, and yields what
the scene displays at any time code, written out from the layer by hand: the drawn copies, which are sheared, and
which placeholders are boxes, with the ways each copy varies and the groupings of time codes a test caches in.
tests/bpy_free/test_time_variations_fixture.py checks these against USD's own APIs at every sampled time code.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from support.time_codes import TimeVariation
from support.usd import open_stage_without_cache

from .scenes import Scene, copy_scene

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pxr import Usd

    from .edit_sequence import CopyIdentity

MOVER, BLINK, SKEW, SHEARING = "/World/Mover", "/World/Blink", "/World/Skew", "/World/Shearing"
GROWS, FLICKER, SCATTER, STILL = "/World/Grows", "/World/Flicker", "/World/Scatter", "/World/Still"


class VaryingAspect(StrEnum):
    """A way a drawn copy's display varies over time, which a cache call keys."""

    TRANSFORM = "transform"  # its world matrix, a sheared copy's split between its shear parent and its object
    VISIBILITY = "visibility"
    SHEAR = "shear"  # a shear that appears or vanishes, so its shear parent is needed only at some time codes
    BOUNDS = "bounds"  # a placeholder box's bounds
    BOUNDS_PRESENCE = "bounds presence"  # a placeholder a box at some time codes and a marker at others
    EXISTENCE = "existence"  # drawn at some time codes only, so it appears or vanishes


def _point(index: int, prototype: str) -> CopyIdentity:
    point = f"{SCATTER}/__index_{index}"
    return (f"{point}/{prototype}", (SCATTER, point))


def _plain(path: str) -> CopyIdentity:
    return (path, ())


def _between(time_code: float | None) -> bool:
    """Whether the time code is in [10, 20), where Scatter has three points and Flicker bounds."""
    return time_code is not None and 10.0 <= time_code < 20.0


@dataclass
class TimeVariationsScene:
    root_layer_path: Path
    stage: Usd.Stage  # the caller's live stage
    variation: TimeVariation
    varying: dict[CopyIdentity, frozenset[VaryingAspect]]  # every copy drawn at some time code; Still varies in none
    synchronized: float  # the time code a test synchronizes at before caching
    # Groupings of time codes to cache, each one call's: the display after every grouping is the same.
    cache_groupings: tuple[tuple[tuple[float, ...], ...], ...]

    def copies(self, time_code: float | None) -> frozenset[CopyIdentity]:
        """The copies drawn at the time code: Scatter's third point and Stone only in [10, 20)."""
        extra = (_point(1, "Stone"), _point(2, "Pebble")) if _between(time_code) else (_point(1, "Pebble"),)
        plain = map(_plain, (MOVER, BLINK, SKEW, SHEARING, GROWS, FLICKER, STILL))
        return frozenset({*plain, _point(0, "Pebble"), *extra})

    def sheared(self, time_code: float | None) -> frozenset[CopyIdentity]:
        """The copies whose world matrix shears them: Skew always, Shearing and Flicker after 10."""
        later = (_plain(SHEARING), _plain(FLICKER)) if time_code is not None and time_code > 10.0 else ()
        return frozenset({_plain(SKEW), *later})

    def boxes(self, time_code: float | None) -> frozenset[CopyIdentity]:
        """The placeholders shown as boxes, the rest markers: Grows always, Flicker in [10, 20)."""
        return frozenset({_plain(GROWS), *((_plain(FLICKER),) if _between(time_code) else ())})

    def blink_visible(self, time_code: float | None) -> bool:
        """Blink is invisible from 10 on; visible at the default time code."""
        return time_code is None or time_code < 10.0


@contextmanager
def time_variations(dest: Path) -> Generator[TimeVariationsScene]:
    """F-TIME-VARIATIONS: see scenes/time_variations/time_variations.usda."""
    root = copy_scene(Scene.TIME_VARIATIONS, dest) / "time_variations.usda"
    aspect = VaryingAspect
    yield TimeVariationsScene(
        root_layer_path=root,
        stage=open_stage_without_cache(root),
        variation=TimeVariation(
            start=0.0, end=20.0, authored_sample_time_codes=(0.0, 10.0, 20.0), transitions=(10.0, 20.0)
        ),
        varying={
            _plain(MOVER): frozenset({aspect.TRANSFORM}),
            _plain(BLINK): frozenset({aspect.VISIBILITY}),
            _plain(SKEW): frozenset({aspect.TRANSFORM}),
            _plain(SHEARING): frozenset({aspect.TRANSFORM, aspect.SHEAR}),
            _plain(GROWS): frozenset({aspect.BOUNDS}),
            _plain(FLICKER): frozenset({aspect.BOUNDS_PRESENCE, aspect.TRANSFORM, aspect.SHEAR}),
            _plain(STILL): frozenset(),
            _point(0, "Pebble"): frozenset(),
            _point(1, "Pebble"): frozenset({aspect.EXISTENCE}),
            _point(1, "Stone"): frozenset({aspect.EXISTENCE}),
            _point(2, "Pebble"): frozenset({aspect.EXISTENCE}),
        },
        synchronized=0.0,
        # One call, the same time codes one at a time in another order, and two calls of mixed size; 12.5 is a
        # subframe.
        cache_groupings=(
            ((5.0, 10.0, 12.5, 15.0, 20.0),),
            ((20.0,), (12.5,), (5.0,), (15.0,), (10.0,)),
            ((15.0, 5.0), (20.0, 12.5, 10.0)),
        ),
    )
