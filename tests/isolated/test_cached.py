"""A cached display (M04-prototypes plan, E3 to E6): structure built once, each frame's values cached as it comes.

The scene is the bridge's frames.usda over M1b's animation case. At each frame visited, the display as Blender
evaluates it holds what a fresh plan at that frame does, meshes whose topology varies included (E4); each frame
synchronizes at its first visit only, until an edit to the stage, after which the display is rebuilt. Every check
runs with the meshes' caches as sample attributes and as a USD file that Mesh Sequence Cache modifiers read (E6).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from .harness import Runtime, run_isolated

if TYPE_CHECKING:
    from collections.abc import Callable

BODY = Path(__file__).parent / "bodies/caching.py"
REOPENING = Path(__file__).parent / "bodies/cache_reopening.py"
# Each frame after the start, revisited, so every frame is cached before it is shown again.
VISITS = {1: [2, 3, 2, 1, 3], 2: [1, 3, 1, 2, 3]}
EDITED_VISITS = [1, 3, 1]
type Copy = tuple[str, tuple[str, ...]]  # source, instance context
SWARM, PIP, PULSE = "/World/Swarm", "/World/Swarm/Protos/Pip", "/World/Swarm/Protos/Pulse"
FLICKER, BULB = "/World/Flicker", "/World/Flicker/Protos/Bulb"
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
    # Flicker's copies change color, which their mesh holds until they differ.
    (BULB, (FLICKER, f"{FLICKER}/__point_0")): ["mesh", "properties"],
    (BULB, (FLICKER, f"{FLICKER}/__point_1")): ["mesh", "properties"],
}
# The copies whose meshes the frames find varying in topology, so they cache whole meshes.
WHOLE = ["/World/Bud", "/World/Morph", "/World/TwinA", "/World/TwinB"]


# Swarm's prototype at each point, by time code.
SWARM_POINTS = {1: [PIP, PIP, PULSE, PULSE], 2: [PIP, PULSE, PULSE, PULSE], 3: [PIP, PULSE, PULSE, PULSE, PIP]}


def _predicted(start: float) -> dict[Copy, list[str]]:
    """What a build at `start` predicts.

    USD reports Steady's points, two equal samples, as time-varying, though the frames find them unchanged. A point
    instancer's per-instance arrays are dirtied as a whole, so each of Swarm's copies at `start` is predicted in
    every aspect its instancer varies in, and in its mesh for Pulse's. Flicker's are predicted in their properties
    alone: their mesh's held color isn't dirtied, so the frames find it.
    """
    predicted = {k: v for k, v in CONFIRMED.items() if k[0] not in (PIP, PULSE, BULB)} | {
        ("/World/Steady", ()): ["mesh"]
    }
    predicted |= {(BULB, (FLICKER, f"{FLICKER}/__point_{point}")): ["properties"] for point in (0, 1)}
    for point, source in enumerate(SWARM_POINTS[int(start)]):
        aspects = ["properties", "transform", "visibility", *(["mesh"] if source == PULSE else [])]
        predicted[(source, (SWARM, f"{SWARM}/__point_{point}"))] = sorted(aspects)
    return predicted


def _copies(aspects: dict[Copy, list[str]]) -> list[list[object]]:
    return sorted([source, list(context), found] for (source, context), found in aspects.items())


# Batched (E5), the scene's pairs batch: copies of one mesh, material slots, object color, and primvar attribute types.
MINIMUM = 2
HAND, HID, TURNED = (
    ("/World/Rig/Arm/Hand", ()),
    ("/World/Shade/Hid/Blade", ("/World/Shade/Hid",)),
    (
        "/World/Spin/Turned/Blade",
        ("/World/Spin/Turned",),
    ),
)


def _point(source: str, point: int) -> Copy:
    instancer = FLICKER if source == BULB else SWARM
    return (source, (instancer, f"{instancer}/__point_{point}"))


def _batches(start: int, predict: bool) -> list[dict[str, Any]]:
    """Each batch's copies once the frames are cached, and its points' varying attributes, sorted.

    A copy is [source, context, whether the batch still holds it], and one it doesn't, whether its object shares
    the batch's prototype's mesh. At 1, Hand, the Blades, Wave, and the twins share a triangle; prediction keeps
    Wave and the twins, which vary in their meshes, apart, and otherwise they leave at 2 as their meshes change,
    onto meshes of their own. At 2, the twins share theirs until TwinB's points move at 3; of the two, the least
    track keeps the batch. Swarm's copies batch by prototype, Pip's only at 1, where it has two; at 1, point 1's
    Pulse and point 4's Pip join their batches. Point 2 leaves Pulse's at 3, as its color changes, still on its
    mesh. Hand and the turned Blade move and the hidden Blade hides; Pip's point 0 moves, and its points hide and
    join only in the viewport, as Pip is a proxy; Pulse's points hide, join, and leave, and point 2 turns only
    once it has left, so its batch's points vary only in their destinations. Flicker's copies leave theirs as
    their color changes, onto a mesh holding the new one.
    """
    shown, moved = ["proscenium_render", "proscenium_viewport"], ["proscenium_transform"]
    triangle: list[list[Any]] = [[*HAND, True], [*HID, True], [*TURNED, True]]
    if start == 1 and not predict:
        triangle += [["/World/Wave", (), False, False], ["/World/TwinA", (), False, False]]
        triangle += [["/World/TwinB", (), False, False]]
    pulse = [[*_point(PULSE, 1), True], [*_point(PULSE, 2), False, True], [*_point(PULSE, 3), True]]
    flicker = [[*_point(BULB, p), False, False] for p in (0, 1)]
    batches: list[tuple[list[list[Any]], list[str]]] = [(triangle, [*shown, *moved]), (pulse, shown)]
    batches.append((flicker, shown))
    if start == 1:
        batches.append(([[*_point(PIP, p), True] for p in (0, 1, 4)], ["proscenium_viewport", *moved]))
    elif not predict:
        batches.append(([["/World/TwinA", (), True], ["/World/TwinB", (), False, False]], shown))
    found = [
        {"tracks": sorted([t[0], list(t[1]), *t[2:]] for t in tracks), "varying": sorted(varying)}
        for tracks, varying in batches
    ]
    return sorted(found, key=lambda b: b["tracks"])


@pytest.mark.parametrize("sequence", [False, True], ids=["attributes", "sequence"])
@pytest.mark.parametrize("minimum", [None, MINIMUM], ids=["objects", "batched"])
@pytest.mark.parametrize("predict", [True, False], ids=["predicted", "unpredicted"])
@pytest.mark.parametrize("start", [1, 2])
def test_cached_frames_match_fresh_plans(  # noqa: PLR0913 - the fixtures, and the display's options
    wheel: Runtime,
    hydra_bridge: Path,
    tmp_path: Path,
    start: int,
    predict: bool,
    minimum: int | None,
    sequence: bool,
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
        minimum=minimum,
        sequence=sequence,
    )
    _check_visits(result["visits"], start, lambda time: time)
    assert result["cached"] == [1, 2, 3]
    assert result["confirmed"] == _copies(CONFIRMED)
    assert result["predicted"] == (_copies(_predicted(start)) if predict else [])
    if minimum is None:
        assert result["whole"] == ([] if sequence else WHOLE)  # a USD mesh's topology varies with time
        # Wave and the twins share Hand's and the Blades' mesh at 1; Wave deforms at 2, and the twins gain a face,
        # sharing theirs until TwinB's points move at 3. Predicted, their meshes are their own from the start.
        assert result["split"] == (0 if predict else 3 if start == 1 else 1)
        assert result["batched"] == []
    else:
        assert result["batched"] == _batches(start, predict)
        # Unpredicted, the twins leave the triangle's batch at 2 as objects of their new topology, which then
        # holds, so they split at 3; built at 2, TwinA's batch caches whole meshes, as their topology at 1 differs.
        unpredicted = ["/World/Bud", "/World/Morph", *([] if start == 1 else ["/World/TwinA"])]
        assert result["whole"] == ([] if sequence else WHOLE if predict else unpredicted)
        assert result["split"] == (1 if not predict and start == 1 else 0)
    # An edit invalidates every cache: the next frame rebuilds, and every other frame synchronizes again.
    assert result["edited"]
    edited = result["edited_visits"]
    assert [v["mismatches"] for v in edited] == [[]] * len(EDITED_VISITS)
    assert [(v["synchronized"], v["rebuilt"]) for v in edited] == [([1], [True]), ([3], [False]), ([], [])]


# Subframes among frames, out of order, each revisited after it is cached.
SUBFRAME_VISITS = [1.5, 2.0, 2.5, 1.25, 1.5, 3.0, 2.5, 1.25, 2.0]


@pytest.mark.parametrize("sequence", [False, True], ids=["attributes", "sequence"])
@pytest.mark.parametrize("minimum", [None, MINIMUM], ids=["objects", "batched"])
@pytest.mark.parametrize("predict", [True, False], ids=["predicted", "unpredicted"])
@pytest.mark.parametrize("subframes", [True, False], ids=["subframes", "frames"])
def test_cached_subframes(  # noqa: PLR0913 - the fixtures, and the display's options
    wheel: Runtime,
    hydra_bridge: Path,
    tmp_path: Path,
    subframes: bool,
    predict: bool,
    minimum: int | None,
    sequence: bool,
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
        start=1.0,
        visits=SUBFRAME_VISITS,
        predict=predict,
        edited_visits=[],
        subframes=subframes,
        minimum=minimum,
        sequence=sequence,
    )
    # With subframes, each is synchronized and shows its own time, between keys of whole frames; without, a
    # subframe synchronizes and shows its frame.
    shown = (lambda time: time) if subframes else (lambda time: float(int(time)))
    _check_visits(result["visits"], 1.0, shown)
    assert result["cached"] == sorted({1.0, *map(shown, SUBFRAME_VISITS)})


@pytest.mark.parametrize("sequence", [False, True], ids=["attributes", "sequence"])
@pytest.mark.parametrize("minimum", [None, MINIMUM], ids=["objects", "batched"])
@pytest.mark.parametrize("start", [1.0, 2.0])
def test_blending_mixes_samples(  # noqa: PLR0913 - the fixtures, and the display's options
    wheel: Runtime, hydra_bridge: Path, tmp_path: Path, start: float, minimum: int | None, sequence: bool
) -> None:
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
        minimum=minimum,
        sequence=sequence,
    )
    # Between cached frames, float attributes mix linearly and the rest hold, and so do meshes cached whole, and
    # in a USD file, an attribute whose sizes differ; built at 1, Wave's samples mix with its own values, as it
    # first varies at 2. Shown times aren't synchronized.
    assert result["synchronized"] == []
    # Batched and built at 1, Flicker's copies leave their batch at 3, onto a mesh holding no color; at 2 it holds
    # their color, an attribute it lacks, so it caches whole meshes.
    assert result["whole"] == ([] if sequence else sorted(WHOLE + ([BULB] if minimum and start == 1 else [])))
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


@pytest.mark.parametrize("sequence", [False, True], ids=["attributes", "sequence"])
def test_reopened_cached_display(wheel: Runtime, hydra_bridge: Path, tmp_path: Path, sequence: bool) -> None:
    dest = tmp_path / "scene"
    dest.mkdir()
    blend = str(tmp_path / "cached.blend")
    times = [1.0, 2.0, 3.0]
    kwargs: dict[str, Any] = {"module_dir": str(hydra_bridge), "dest": str(dest), "blend": blend, "times": times}
    for run in ("saved", "reopened", "missing"):  # each process's own directory
        (tmp_path / run).mkdir()
    saved = run_isolated(wheel, REOPENING, "save", tmp_path / "saved", **kwargs, sequence=sequence)
    kwargs["objects"] = saved["objects"]
    # Reopened with no bridge, the display plays back its cached frames: from the .blend, or with sequence, from
    # its USD file as well.
    reopened = run_isolated(wheel, REOPENING, "reopen", tmp_path / "reopened", **kwargs, remove=None)
    assert reopened["mismatches"] == {str(t): [] for t in times}
    if not sequence:
        return
    # Without the file, each mesh that varies shows its own content, the build's, at every time, and the rest of
    # the display is unchanged.
    missing = run_isolated(wheel, REOPENING, "reopen", tmp_path / "missing", **kwargs, remove=saved["cache"])
    assert missing["mismatches"]["1.0"] == []
    varying = {copy[0] for copy, aspects in CONFIRMED.items() if {"mesh", "bounds"} & set(aspects)}
    differing = set()
    for time in times[1:]:
        found = missing["mismatches"][str(time)]
        assert not [m for m in found if m.endswith(": transform") or ": shown" in m or ": no object" in m], time
        differing |= {m.split("'")[1] for m in found}
    assert differing == varying - {"/World/Skinned/Skel"}  # whose mesh shows in neither destination
