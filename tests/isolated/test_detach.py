"""M4's detach walkthrough in the object baseline (M04-prototypes plan, B7), under Detach As-Is.

The bridge's detach.py releases an applied display after Blender-side edits. It must remove the binding's own
ID properties, which all start with "proscenium_", and keep everything else as it was, edits included. The
saved result must reopen the same in a process without the bridge.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from fixtures import appearance, interaction

from .harness import Runtime, run_isolated

if TYPE_CHECKING:
    from collections.abc import Generator

BODY = Path(__file__).parent / "bodies/baseline.py"
BINDING = "proscenium_"  # the prefix of every ID property the baseline adds for itself


@pytest.fixture(params=["appearance", "stress", "universe"])
def scene(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[tuple[str, Path]]:
    # F-UNIVERSE-MEMBERSHIP has a placeholder drawn as bounds and an empty marker.
    generators = {
        "appearance": appearance.appearance_cases,
        "stress": appearance.nested_stress,
        "universe": interaction.universe_membership,
    }
    with generators[request.param](tmp_path) as built:
        yield request.param, built.root


def test_detach_removes_only_binding_metadata(
    scene: tuple[str, Path], wheel: Runtime, hydra_bridge: Path, tmp_path: Path
) -> None:
    name, root = scene
    blend = tmp_path / "detached.blend"
    kwargs: dict[str, Any] = {"module_dir": str(hydra_bridge), "scene": str(root), "blend": str(blend)}
    result = run_isolated(wheel, BODY, "detach_scene", tmp_path, **kwargs)
    before, after = result["before"], result["after"]
    # The edits made before detach, which it keeps.
    assert result["deleted"] not in before["objects"]
    if result["recolored"] is not None:
        assert before["materials"][result["recolored"]]["diffuse"] == [1.0, 0.0, 1.0, 1.0]

    if name == "universe":  # the placeholders, which detach keeps as ordinary objects
        placeholders = [o for o in before["objects"].values() if "proscenium_placeholder" in o["properties"]]
        shown = sorted((o["type"], o["display"][0] if o["type"] == "MESH" else o["display"][1]) for o in placeholders)
        assert shown == [("EMPTY", "PLAIN_AXES"), ("MESH", "BOUNDS")]

    assert after == _without_binding(before)
    released = result["released"]
    assert released["objects"] == sum(1 for o in before["objects"].values() if _binding_keys(o))
    assert released["materials"] == sum(1 for m in before["materials"].values() if _binding_keys(m))
    kinds = ("objects", "meshes", "materials")
    assert released["properties"] == sum(len(_binding_keys(d)) for kind in kinds for d in before[kind].values())
    assert released["objects"] > 0

    reopened = run_isolated(wheel, BODY, "read_blend", tmp_path, blend=str(blend))
    assert reopened == after


def _binding_keys(datablock: dict[str, Any]) -> list[str]:
    return [key for key in datablock["properties"] if key.startswith(BINDING)]


def _without_binding(data: dict[str, Any]) -> dict[str, Any]:
    stripped = {kind: dict(entries) for kind, entries in data.items()}
    for kind in ("objects", "meshes", "materials"):
        for name, entry in data[kind].items():
            properties = {k: v for k, v in entry["properties"].items() if not k.startswith(BINDING)}
            stripped[kind][name] = {**entry, "properties": properties}
    return stripped
