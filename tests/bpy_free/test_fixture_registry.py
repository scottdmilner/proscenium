"""The fixture registry and scene index match the docs and the files, and the generators run."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fixtures.registry import FIXTURES
from fixtures.scenes import SCENES, Scene
from matrix import milestone_of

DOCS = Path(__file__).parents[2] / "docs"
ID = re.compile(r"`(F-[A-Z-]+)`")


def _strategy_ids() -> list[str]:
    """IDs in the Named Contract Fixtures table of strategy.md, in order."""
    text = (DOCS / "testing" / "strategy.md").read_text(encoding="utf-8")
    table = text.split("## Named Contract Fixtures", 1)[1].split("\n## ", 1)[0]
    return [m.group(1) for line in table.splitlines() if line.startswith("| `F-") and (m := ID.search(line))]


def _milestones_naming(fixture_id: str) -> set[str]:
    """Milestones whose **Tests:** section names the fixture."""
    found = set()
    for path in (DOCS / "milestones").glob("M*.md"):
        text = path.read_text(encoding="utf-8")
        if "**Tests:**" not in text:
            continue
        tests = text.split("**Tests:**", 1)[1].split("\n**", 1)[0]
        if f"`{fixture_id}`" in tests:
            found.add(milestone_of(path) or path.name)  # M01b-... -> M1b
    return found


def test_registry_lists_every_named_fixture_in_order() -> None:
    assert list(FIXTURES) == _strategy_ids()


@pytest.mark.parametrize("fixture_id", list(FIXTURES))
def test_milestones_match_milestone_tests_sections(fixture_id: str) -> None:
    assert set(FIXTURES[fixture_id].milestones) == _milestones_naming(fixture_id)


@pytest.mark.parametrize("fixture_id", [f.id for f in FIXTURES.values() if f.build is not None])
def test_generators_build_and_release(fixture_id: str, tmp_path: Path) -> None:
    build = FIXTURES[fixture_id].build
    assert build is not None
    with build(tmp_path) as scene:
        assert scene is not None


def test_scene_index_matches_directories() -> None:
    directories = {p.name for p in SCENES.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert directories == {scene.value for scene in Scene}


@pytest.mark.parametrize("layer", sorted(SCENES.rglob("*.usda")), ids=lambda p: p.relative_to(SCENES).as_posix())
def test_scene_layers_state_their_purpose(layer: Path) -> None:
    # Static layers start with a comment saying what they are for (AGENTS.md#style).
    lines = layer.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "#usda 1.0"
    assert len(lines) > 1 and lines[1].startswith("# "), "line 2 must be a purpose comment"
