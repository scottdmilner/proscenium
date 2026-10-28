"""M4's plan diff (M04-prototypes plan, C1): what a new plan changes from the published one.

Each step edits the caller's stage, recaptures incrementally, and diffs the new plan against the previous one.
What each edit changes comes from how the fixture is built: the objects of the edited prims, the copies of an
edited prototype mesh, the meshes bound to an edited material, and the contents of a payload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fixtures import appearance, interaction

from .harness import Runtime, run_isolated

BODY = Path(__file__).parent / "bodies/plan_diff.py"
EQUAL = "/World/EqualContent"
RED = "/World/Looks/Red"
PAYLOAD = "/World/Payload"


def _steps(scene: Path, edits: list[str], wheel: Runtime, hydra_bridge: Path, tmp_path: Path) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"module_dir": str(hydra_bridge), "scene": str(scene), "edits": edits}
    steps = run_isolated(wheel, BODY, "diff_edits", tmp_path, **kwargs)
    return {step["edit"]: step for step in steps}


def _changes(step: dict[str, Any]) -> dict[str, Any]:
    """What the diff reports, by source, after checking that it matches objects only to their own source."""
    diff, old, new = step["diff"], step["old"], step["new"]
    assert len(diff["objects"]) == len(new)
    for index, match in enumerate(diff["objects"]):
        if match != -1:
            assert old[match]["source"] == new[index]["source"], index
    matched = {m for m in diff["objects"] if m != -1}
    assert sorted(set(range(len(old))) - matched) == diff["removed"]
    return {
        "added": {new[i]["source"] for i, m in enumerate(diff["objects"]) if m == -1},
        "removed": {old[i]["source"] for i in diff["removed"]},
        "changed": {new[i]["source"] for i in diff["changed"]},
        "new meshes": sum(1 for m in diff["meshes"] if m == -1),
        "new materials": [step["materials"][i] for i, m in enumerate(diff["materials"]) if m == -1],
    }


NOTHING = {"added": set(), "removed": set(), "changed": set(), "new meshes": 0, "new materials": []}


def test_diff_follows_edits(wheel: Runtime, hydra_bridge: Path, tmp_path: Path) -> None:
    edits = ["unchanged", "transform", "shared-geometry", "material", "primvar", "visibility", "structure"]
    with appearance.appearance_cases(tmp_path / "scene") as cases:
        steps = _steps(cases.root, edits, wheel, hydra_bridge, tmp_path)
    assert _changes(steps["unchanged"]) == NOTHING
    assert _changes(steps["transform"]) == {**NOTHING, "changed": {f"{EQUAL}/MeshD"}}
    (bodies,) = (uses for uses in cases.shared if any(path.endswith("/Body") for path in uses))
    assert _changes(steps["shared-geometry"]) == {**NOTHING, "changed": set(bodies), "new meshes": 1}

    red = {mesh for mesh, bound in cases.materials.items() if RED in bound}
    red |= {mesh for mesh, faces in cases.face_materials.items() if RED in faces}
    material = _changes(steps["material"])
    assert material["new materials"], "the edited material must be rebuilt"
    assert all(RED in sources for sources in material["new materials"])
    assert {**material, "new materials": []} == {**NOTHING, "changed": red}

    assert _changes(steps["primvar"]) == {**NOTHING, "changed": {f"{EQUAL}/MeshB"}}  # its object color
    # An object's identity includes the destinations it displays in, so a hidden copy is another object.
    assert _changes(steps["visibility"]) == {**NOTHING, "added": {f"{EQUAL}/MeshA"}, "removed": {f"{EQUAL}/MeshA"}}
    structure = {**NOTHING, "added": {f"{EQUAL}/MeshNew"}, "removed": {f"{EQUAL}/MeshC"}}
    assert _changes(steps["structure"]) == structure  # MeshNew has MeshA's content, and MeshC's mesh stays


def test_diff_follows_payload_loading(wheel: Runtime, hydra_bridge: Path, tmp_path: Path) -> None:
    with interaction.universe_membership(tmp_path / "scene") as scene:
        steps = _steps(scene.root, ["unload", "load"], wheel, hydra_bridge, tmp_path)
    contents = {o["source"] for o in steps["unload"]["old"] if o["source"].startswith(f"{PAYLOAD}/")}
    assert contents
    assert _changes(steps["unload"]) == {**NOTHING, "removed": contents}
    assert _changes(steps["load"]) == {**NOTHING, "added": contents}


def test_unchanged_stress_plan_matches_everything(wheel: Runtime, hydra_bridge: Path, tmp_path: Path) -> None:
    # Sheared and mirrored copies, and copies shown in one destination or neither, all matched unchanged.
    with appearance.nested_stress(tmp_path / "scene") as stress:
        steps = _steps(stress.root, ["unchanged"], wheel, hydra_bridge, tmp_path)
    assert _changes(steps["unchanged"]) == NOTHING
