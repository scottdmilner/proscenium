"""A cached display (M04-prototypes plan, E3, E4): structure built once, each frame's varying values cached as it comes.

The scene is the bridge's frames.usda over M1b's animation case. At each frame visited, the display as Blender
evaluates it holds what a fresh plan at that frame does, meshes whose topology varies included (E4); each frame
synchronizes at its first visit only, until an edit to the stage, after which the display is rebuilt.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from .harness import Runtime, run_isolated

if TYPE_CHECKING:
    from collections.abc import Callable

BODY = Path(__file__).parent / "bodies/caching.py"
# Each frame after the start, revisited, so every frame is cached before it is shown again.
VISITS = {1: [2, 3, 2, 1, 3], 2: [1, 3, 1, 2, 3]}
EDITED_VISITS = [1, 3, 1]
type Copy = tuple[str, tuple[str, ...]]  # source, instance context
SWARM, PIP, PULSE = "/World/Swarm", "/World/Swarm/Protos/Pip", "/World/Swarm/Protos/Pulse"
# By copy: what animation.usda's and frames.usda's comments say varies.
CONFIRMED: dict[Copy, list[str]] = {
    ("/World/Wave", ()): ["mesh"],
    ("/World/Rig/Arm/Hand", ()): ["transform"],
    ("/World/Spin/Turned/Blade", ("/World/Spin/Turned",)): ["transform"],
    ("/World/Blinker", ()): ["visibility"],
    ("/World/Shade/Shaded", ()): ["visibility"],
    ("/World/Shade/Hid/Blade", ("/World/Shade/Hid",)): ["visibility"],
    ("/World/Tinted", ()): ["mesh", "properties"],  # held displayColor, and the level primvar
    ("/World/Remapped", ()): ["mesh"],
    ("/World/Tagged", ()): ["mesh"],
    ("/World/Split", ()): ["mesh"],  # its faces' material slots
    ("/World/Aid", ()): ["visibility"],
    ("/World/Comb", ()): ["transform"],
    ("/World/Strands", ()): ["bounds"],
    ("/World/Skinned/Body", ()): ["mesh"],
    ("/World/Skinned/Skel", ()): ["mesh"],
    ("/World/Dual", ()): ["visibility"],
    ("/World/Roam", ()): ["mesh", "transform"],
    ("/World/Lean", ()): ["transform"],
    ("/World/Guides/Guided", ()): ["visibility"],
    ("/World/Morph", ()): ["mesh"],  # gains a face
    ("/World/Bud", ()): ["mesh"],  # its points move, then its face is rewound
    ("/World/TwinA", ()): ["mesh"],
    ("/World/TwinB", ()): ["mesh"],
    # Swarm's copies (E5): point 0 moves, point 1 is a Pip at 1 and a Pulse from 2, point 3 is invisible at 2,
    # point 4 appears at 3, and point 2 turns and changes heat at 3; Pulse's points move.
    (PIP, (SWARM, f"{SWARM}/__point_0")): ["transform"],
    (PIP, (SWARM, f"{SWARM}/__point_1")): ["visibility"],
    (PULSE, (SWARM, f"{SWARM}/__point_1")): ["mesh", "visibility"],
    (PULSE, (SWARM, f"{SWARM}/__point_2")): ["mesh", "properties", "transform"],
    (PULSE, (SWARM, f"{SWARM}/__point_3")): ["mesh", "visibility"],
    (PIP, (SWARM, f"{SWARM}/__point_4")): ["visibility"],
}
# The copies whose meshes the frames find varying in topology, so they cache whole meshes.
WHOLE = ["/World/Bud", "/World/Morph", "/World/TwinA", "/World/TwinB"]


# Swarm's prototype at each point, by time code.
SWARM_POINTS = {1: [PIP, PIP, PULSE, PULSE], 2: [PIP, PULSE, PULSE, PULSE], 3: [PIP, PULSE, PULSE, PULSE, PIP]}


def _predicted(start: float) -> dict[Copy, list[str]]:
    """What a build at `start` predicts.

    USD reports Steady's points, two equal samples, as time-varying, though the frames find them unchanged. A point
    instancer's per-instance arrays are dirtied as a whole, so each of Swarm's copies at `start` is predicted in
    every aspect its instancer varies in, and in its mesh for Pulse's.
    """
    predicted = {k: v for k, v in CONFIRMED.items() if k[0] not in (PIP, PULSE)} | {("/World/Steady", ()): ["mesh"]}
    for point, source in enumerate(SWARM_POINTS[int(start)]):
        aspects = ["properties", "transform", "visibility", *(["mesh"] if source == PULSE else [])]
        predicted[(source, (SWARM, f"{SWARM}/__point_{point}"))] = sorted(aspects)
    return predicted


def _copies(aspects: dict[Copy, list[str]]) -> list[list[object]]:
    return sorted([source, list(context), found] for (source, context), found in aspects.items())


@pytest.mark.parametrize("predict", [True, False], ids=["predicted", "unpredicted"])
@pytest.mark.parametrize("start", [1, 2])
def test_cached_frames_match_fresh_plans(
    wheel: Runtime, hydra_bridge: Path, tmp_path: Path, start: int, predict: bool
) -> None:
    dest = tmp_path / "scene"
    dest.mkdir()
    result = run_isolated(
        wheel,
        BODY,
        "follow",
        tmp_path,
        module_dir=str(hydra_bridge),
        dest=str(dest),
        start=start,
        visits=VISITS[start],
        predict=predict,
        edited_visits=EDITED_VISITS,
    )
    _check_visits(result["visits"], start, lambda time: time)
    assert result["cached"] == [1, 2, 3]
    assert result["confirmed"] == _copies(CONFIRMED)
    assert result["predicted"] == (_copies(_predicted(start)) if predict else [])
    assert result["whole"] == WHOLE
    # Wave and the twins share Hand's and the Blades' mesh at 1; Wave deforms at 2, and the twins gain a face,
    # sharing theirs until TwinB's points move at 3. Predicted, their meshes are their own from the start.
    assert result["split"] == (0 if predict else 3 if start == 1 else 1)
    # An edit invalidates every cache: the next frame rebuilds, and every other frame synchronizes again.
    assert result["edited"]
    edited = result["edited_visits"]
    assert [v["mismatches"] for v in edited] == [[]] * len(EDITED_VISITS)
    assert [(v["synchronized"], v["rebuilt"]) for v in edited] == [([1], [True]), ([3], [False]), ([], [])]


# Subframes among frames, out of order, each revisited after it is cached.
SUBFRAME_VISITS = [1.5, 2.0, 2.5, 1.25, 1.5, 3.0, 2.5, 1.25, 2.0]


@pytest.mark.parametrize("predict", [True, False], ids=["predicted", "unpredicted"])
@pytest.mark.parametrize("subframes", [True, False], ids=["subframes", "frames"])
def test_cached_subframes(wheel: Runtime, hydra_bridge: Path, tmp_path: Path, subframes: bool, predict: bool) -> None:
    dest = tmp_path / "scene"
    dest.mkdir()
    result = run_isolated(
        wheel,
        BODY,
        "follow",
        tmp_path,
        module_dir=str(hydra_bridge),
        dest=str(dest),
        start=1.0,
        visits=SUBFRAME_VISITS,
        predict=predict,
        edited_visits=[],
        subframes=subframes,
    )
    # With subframes, each is synchronized and shows its own time, between keys of whole frames; without, a
    # subframe synchronizes and shows its frame.
    shown = (lambda time: time) if subframes else (lambda time: float(int(time)))
    _check_visits(result["visits"], 1.0, shown)
    assert result["cached"] == sorted({1.0, *map(shown, SUBFRAME_VISITS)})


@pytest.mark.parametrize("start", [1.0, 2.0])
def test_blending_mixes_samples(wheel: Runtime, hydra_bridge: Path, tmp_path: Path, start: float) -> None:
    dest = tmp_path / "scene"
    dest.mkdir()
    synchronized = [start, *(t for t in (3.0, 1.0, 2.0) if t != start)]
    result = run_isolated(
        wheel,
        BODY,
        "blended",
        tmp_path,
        module_dir=str(hydra_bridge),
        dest=str(dest),
        synchronized=synchronized,
        shown=[1.5, 2.25, 1.75, 2.75],
    )
    # Between cached frames, float attributes mix linearly and the rest hold, and so do meshes cached whole;
    # built at 1, Wave's samples mix with its own values, as it first varies at 2. Shown times aren't synchronized.
    assert result["synchronized"] == []
    assert result["whole"] == WHOLE
    assert result["unresolved"] == []  # no key left on an input that a whole mesh's group lacks
    for visit in result["visits"]:
        assert visit["mismatches"] == [], visit["time"]
    assert [v["between"] for v in result["visits"]] == [[1, 2], [2, 3], [1, 2], [2, 3]]


def _check_visits(visits: list[dict[str, Any]], start: float, shown: Callable[[float], float]) -> None:
    """Each visit holds what a fresh plan does at the time it shows, synchronized there at its first visit only."""
    seen = {start}
    for visit in visits:
        time = shown(visit["time"])
        assert visit["mismatches"] == [], visit["time"]
        assert visit["synchronized"] == ([] if time in seen else [time]), visit["time"]
        assert visit["rebuilt"] == [False] * len(visit["synchronized"]), visit["time"]
        seen.add(time)


@pytest.mark.parametrize("time", [1.0, 2.0])
def test_prediction_leaves_capture_unchanged(wheel: Runtime, hydra_bridge: Path, tmp_path: Path, time: float) -> None:
    dest = tmp_path / "scene"
    dest.mkdir()
    result = run_isolated(
        wheel, BODY, "predicting", tmp_path, module_dir=str(hydra_bridge), dest=str(dest), time=time, later=3.0
    )
    # The same plan but for its dirtied aspects: those that depend on time, Morph's topology included, which are
    # what a real time change dirties; a plain capture dirties nothing.
    assert result["same_plan"]
    assert result["dirtied_aspects"] == _copies(_predicted(time) | {("/World/Morph", ()): ["mesh"]})
    assert result["later_dirtied_aspects"] == _copies(_predicted(3.0) | {("/World/Morph", ()): ["mesh"]})
    assert result["plain_dirtied_aspects"] == []
    # Hydra still dirties the same locators when the time changes next.
    assert result["same_dirtied_locators"]
