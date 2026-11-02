"""Frames captured over a range (M04-prototypes plan, E1): each drawn copy's objects followed across frames.

The scene is the bridge's frames.usda over M1b's animation case. What varies along each track comes from how
the scene is built: animation.usda's comment says which value of each prim varies over [1, 3], and frames.usda's
which destinations its copy's objects show in.
"""

from __future__ import annotations

from pathlib import Path

from .harness import Runtime, run_isolated

BODY = Path(__file__).parent / "bodies/animation.py"
TIMES = [1.0, 2.0, 3.0]
SWARM, PIP, PULSE = "/World/Swarm", "/World/Swarm/Protos/Pip", "/World/Swarm/Protos/Pulse"
# By track (source, instance context, place among the copy's objects): what varies over the frames.
VARYING = {
    ("/World/Wave", (), 0): {"mesh"},  # points
    ("/World/Rig/Arm/Hand", (), 0): {"transform"},  # an ancestor's translation
    ("/World/Spin/Turned/Blade", ("/World/Spin/Turned",), 0): {"transform"},  # its instance root's ancestor's
    ("/World/Blinker", (), 0): {"visibility"},
    ("/World/Shade/Shaded", (), 0): {"visibility"},  # an ancestor's
    ("/World/Shade/Hid/Blade", ("/World/Shade/Hid",), 0): {"visibility"},
    ("/World/Morph", (), 0): {"mesh"},  # topology
    # A constant displayColor that its mesh's one copy has, so the mesh holds it (D13), and a held int primvar.
    ("/World/Tinted", (), 0): {"mesh", "properties"},
    ("/World/Remapped", (), 0): {"mesh"},  # an indexed primvar's indices
    ("/World/Tagged", (), 0): {"mesh"},  # a uniform primvar
    ("/World/Split", (), 0): {"mesh"},  # its subsets' faces, which are its faces' material slots
    ("/World/Aid", (), 0): {"visibility"},  # guideVisibility, in the viewport
    ("/World/Comb", (), 0): {"transform"},  # a placeholder
    ("/World/Strands", (), 0): {"bounds"},  # a placeholder's computed extent
    ("/World/Skinned/Body", (), 0): {"mesh"},  # skinned points
    ("/World/Skinned/Skel", (), 0): {"mesh"},  # the bone mesh's points follow the joints
    ("/World/Dual", (), 0): {"visibility"},  # its viewport object, hidden at 2
    ("/World/Dual", (), 1): {"visibility"},  # its render object, absent at 2
    ("/World/Roam", (), 0): {"mesh", "transform"},
    ("/World/Lean", (), 0): {"transform"},  # sheared from just after 1
    ("/World/Guides/Guided", (), 0): {"visibility"},  # an ancestor's guideVisibility
    ("/World/Bud", (), 0): {"mesh"},  # points, then corners
    ("/World/TwinA", (), 0): {"mesh"},  # topology
    ("/World/TwinB", (), 0): {"mesh"},  # topology, then points
    # Swarm's copies, by point (E5): point 1's Pip and Pulse copies come and go with protoIndices, point 3 is
    # invisible at 2, point 4 appears at 3, and Pulse's points move.
    (PIP, (SWARM, f"{SWARM}/__point_0"), 0): {"transform"},
    (PIP, (SWARM, f"{SWARM}/__point_1"), 0): {"visibility"},
    (PULSE, (SWARM, f"{SWARM}/__point_1"), 0): {"mesh", "visibility"},
    (PULSE, (SWARM, f"{SWARM}/__point_2"), 0): {"mesh", "properties", "transform"},
    (PULSE, (SWARM, f"{SWARM}/__point_3"), 0): {"mesh", "visibility"},
    (PIP, (SWARM, f"{SWARM}/__point_4"), 0): {"visibility"},
    ("/World/Steady", (), 0): set(),  # two equal samples
    ("/World/Single", (), 0): set(),  # one sample
    ("/World/Still", (), 0): set(),
}


def test_tracks_follow_each_copys_objects(wheel: Runtime, hydra_bridge: Path, tmp_path: Path) -> None:
    dest = tmp_path / "scene"
    dest.mkdir()
    result = run_isolated(wheel, BODY, "capture", tmp_path, module_dir=str(hydra_bridge), dest=str(dest), times=TIMES)
    tracks = {(key[0], tuple(key[1]), key[2]): track for track in result["tracks"] for key in [track["key"]]}
    assert {key: set(track["varying"]) for key, track in tracks.items()} == VARYING
    # At each frame, a fresh bridge's objects are exactly the tracks' objects, each the record its track holds
    # there, with a copy's second object following its first.
    for frame, objects in enumerate(result["frames"]):
        indices = sorted(t["objects"][frame] for t in tracks.values() if t["objects"][frame] is not None)
        assert indices == list(range(len(objects))), frame
        for (source, _, place), track in tracks.items():
            index = track["objects"][frame]
            if index is None:
                assert track["records"][frame] is None, (frame, source)
                continue
            assert track["records"][frame] == objects[index], (frame, source)
            if place:
                assert objects[index - 1][:2] == objects[index][:2], (frame, source)
    dual = [tracks[("/World/Dual", (), place)]["objects"] for place in (0, 1)]
    assert [index is None for index in dual[1]] == [False, True, False]
    viewport, render = (result["frames"][1][dual[0][1]][2:4], result["frames"][0][dual[1][0]][2:4])
    assert (viewport, render) == ([False, False], [False, True])  # hidden at 2; the render object at 1
