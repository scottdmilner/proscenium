"""The inspection layer through the core's correspondence: selection targets by kind on the live stage.

The library is the core's `inspection/` directory, which has no Python bindings, so it is checked through
`select_targets` and `selection_from_blender`, and by reading its sources and build. Expected targets come from the
interaction fixtures and support/interaction_oracle.py, which reads kinds with Usd.ModelAPI and Kind.Registry.
support/interaction_checks.py checks the same functions against the real display in tests/blender.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from fixtures import interaction
from proscenium.core import _core
from support import interaction_oracle

from .plan_checks import plan_at

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from pxr import Usd

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "proscenium" / "core"
INSPECTION = CORE / "inspection"
SCENES: dict[str, Callable[[Path], AbstractContextManager[interaction.InteractionScene]]] = {
    "F-KIND-HIERARCHY": interaction.kind_hierarchy,
    "F-NESTED-SELECTION": interaction.nested_selection,
    "F-UNIVERSE-MEMBERSHIP": interaction.universe_membership,
}


def _correspondence(stage: Usd.Stage, plan: _core.Plan) -> _core.Correspondence:
    entries = plan.correspondence
    return _core.Correspondence(
        stage,
        [e.source_path for e in entries],
        [e.instance_context for e in entries],
        [bool(v) for v in memoryview(plan.copy_visible_in_viewport).tolist()],
    )


@pytest.mark.parametrize("fixture", ["F-KIND-HIERARCHY", "F-NESTED-SELECTION"])
def test_targets_at_every_level(tmp_path: Path, fixture: str) -> None:
    # ICON-18, ICON-20, ICON-21: each element's, and each of the fixture's cases' entities', target at the prim level
    # and at every registered kind is the oracle's, outside a valid model hierarchy and inside instances included.
    with SCENES[fixture](tmp_path) as scene:
        stage = scene.stage
        correspondence = _correspondence(stage, plan_at(stage, scene.times[0]))
        paths = sorted(scene.elements[scene.times[0]] | {path for path, _ in scene.kind_targets})
        for level in interaction_oracle.levels():
            expected = [interaction_oracle.kind_target(stage, interaction_oracle.floor(stage, p), level) for p in paths]
            assert list(correspondence.select_targets(paths, level)) == expected, level
        for (path, level), target in scene.kind_targets.items():
            assert correspondence.select_targets([path], level) == (target,), (path, level)


@pytest.mark.parametrize("fixture", ["F-KIND-HIERARCHY", "F-NESTED-SELECTION"])
def test_an_absent_floor_is_its_own_target(tmp_path: Path, fixture: str) -> None:
    # ICON-21: at a kind level, an entity whose floor the live stage no longer has targets its floor.
    with SCENES[fixture](tmp_path) as scene:
        assert scene.absent_floor is not None
        removed, path, level = scene.absent_floor
        stage = scene.stage
        correspondence = _correspondence(stage, plan_at(stage, scene.times[0]))
        floor = interaction_oracle.floor(stage, path)
        stage.RemovePrim(removed)
        assert not stage.GetPrimAtPath(floor)
        assert correspondence.select_targets([path], level) == (floor,)


def test_a_level_must_be_a_registered_kind(tmp_path: Path) -> None:
    # ICON-18: the prim level and registered kinds only.
    with interaction.kind_hierarchy(tmp_path) as scene:
        correspondence = _correspondence(scene.stage, plan_at(scene.stage, 0.0))
        for call in (
            lambda: correspondence.select_targets(["/World"], "furniture"),
            lambda: correspondence.selection_from_blender([0], None, "furniture"),
        ):
            with pytest.raises(ValueError, match="not a registered kind"):
                call()


def test_selection_from_blender_gives_each_target_once(tmp_path: Path) -> None:
    # ICON-30 at the core: the selected elements' targets at the level, in their order, each once, the active one's
    # target active, and indices naming no element ignored.
    with interaction.kind_hierarchy(tmp_path) as scene:
        plan = plan_at(scene.stage, 0.0)
        correspondence = _correspondence(scene.stage, plan)
        index = {e.source_path: i for i, e in enumerate(plan.correspondence)}
        seat, back, top = "/World/Props/Chair/Geom/Seat", "/World/Props/Chair/Geom/Back", "/World/Table/Top"
        selected = [index[seat], len(index), index[top], index[back]]
        selection = correspondence.selection_from_blender(selected, index[back], "component")
        assert selection.target_paths == ("/World/Props/Chair", "/World/Table")  # Table is a component
        assert selection.active_target_path == "/World/Props/Chair"
        prim_level = correspondence.selection_from_blender(selected, None, None)
        assert prim_level.target_paths == (seat, top, back)
        assert prim_level.active_target_path is None


@pytest.mark.parametrize("fixture", ["F-KIND-HIERARCHY", "F-UNIVERSE-MEMBERSHIP"])
def test_kind_levels_leave_the_stage_unchanged(tmp_path: Path, fixture: str) -> None:
    # ICON-06: kind-level select_targets and selection_from_blender leave the stage's layers clean and unchanged, and
    # its load set and population mask as they were.
    with SCENES[fixture](tmp_path) as scene:
        stage = scene.stage

        def state() -> tuple[Any, ...]:
            layers = sorted((layer.identifier, layer.ExportToString(), layer.dirty) for layer in stage.GetUsedLayers())
            return layers, sorted(map(str, stage.GetLoadSet())), stage.GetPopulationMask()

        before = state()
        for time in scene.times:
            correspondence = _correspondence(stage, plan_at(stage, time))
            paths = sorted(scene.elements[time])
            for level in interaction_oracle.levels()[1:]:
                correspondence.select_targets(paths, level)
                correspondence.selection_from_blender(range(correspondence.element_count), 0, level)
        assert state() == before


def _includes(path: Path) -> list[str]:
    return re.findall(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', path.read_text(), flags=re.MULTILINE)


def _in_this_checkout(path: Path, built_checkout: Path) -> Path:
    """A path the core's build recorded, moved from the checkout it was built in to this one."""
    return ROOT / path.relative_to(built_checkout) if path.is_relative_to(built_checkout) else path


def test_the_inspection_layer_reads_only_usd() -> None:
    # ICON-04: the library's sources include only USD's headers, the standard library's, and its own; its build
    # target links only Blender's USD; and its compile commands' include directories are its own and USD's with
    # USD's dependencies (TBB, and Python, which Blender builds USD with), none of the core's.
    sources = sorted([*INSPECTION.glob("*.cpp"), *INSPECTION.glob("*.h")])
    assert sources
    own = {p.name for p in sources}
    for source in sources:
        for header in _includes(source):
            assert header.startswith("pxr/") or header in own or "." not in header, (source.name, header)
    cmake = (INSPECTION / "CMakeLists.txt").read_text()
    assert re.findall(r"target_link_libraries\(([^)]*)\)", cmake) == ['proscenium_inspection PRIVATE "${USD_LIBRARY}"']
    # CI's Linux tests read the compile commands core-linux built with, whose paths are its container's checkout.
    commands = json.loads((ROOT / "build" / "core-cmake" / "compile_commands.json").read_text())
    inspection_commands = []
    for command in commands:
        # Each command runs in the build directory, build/core-cmake under the checkout it was built in.
        built_checkout = Path(command["directory"]).parents[1]
        source = _in_this_checkout(Path(command["file"]), built_checkout)
        if source.parent == INSPECTION:
            inspection_commands.append((source, command, built_checkout))
    assert {source.name for source, _, _ in inspection_commands} == {p.name for p in sources if p.suffix == ".cpp"}
    for source, command, built_checkout in inspection_commands:
        arguments = command.get("arguments") or command["command"].split()
        directories = [a.removeprefix("-I") for a in arguments if a.startswith("-I") and a != "-I"]
        directories += [arguments[i + 1] for i, a in enumerate(arguments) if a in {"-isystem", "-I"}]
        assert directories, source.name
        for directory in (_in_this_checkout(Path(d), built_checkout) for d in directories):
            assert directory == INSPECTION or re.search(
                r"/(usd|tbb|python)/include(/python3\.\d+)?$", directory.as_posix()
            ), directory


def _inspection_functions() -> set[str]:
    """The functions the inspection layer's headers declare."""
    names: set[str] = set()
    for header in INSPECTION.glob("*.h"):
        names |= set(re.findall(r"^[\w:<>]+[\s&*]+(\w+)\(", header.read_text(), flags=re.MULTILINE))
    return names


def test_the_core_exposes_no_inspection_function() -> None:
    # ICON-05: the core's bindings and stubs expose the interaction functions and none of the inspection layer's, so
    # a kind-level select_targets reaches the inspection layer in C++.
    functions = _inspection_functions()
    assert functions >= {"KindTarget", "IsRegisteredKind"}
    snake = {re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower() for name in functions}
    exposed = {name.lower() for name in dir(_core)} | {
        name.lower() for name in dir(_core.Correspondence) if not name.startswith("__")
    }
    assert not exposed & snake
    stub = (CORE / "_core.pyi").read_text()
    assert not any(re.search(rf"\bdef {name}\b", stub) for name in snake)
    bindings = (CORE / "python_bindings.cpp").read_text()
    assert "kind_targets.h" not in bindings
    assert "proscenium_inspection" not in bindings
    interaction_functions = {
        "resolve_pick",
        "displayed",
        "highlight_targets",
        "select_targets",
        "selection_from_blender",
    }
    assert interaction_functions <= set(dir(_core.Correspondence))
