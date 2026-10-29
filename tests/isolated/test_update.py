"""M4's small updates in the object baseline (M04-prototypes plan, B6): replacing one unit of a published display.

The bridge's update.py prepares a unit beside the display, publishes it, and retires what it replaced. Each case
replaces the unit from the same plan, so the display must hold what it held before, with new data exactly where
the unit and its user policy say, and nothing left over.
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
POINTERS = ("pointer", "data_pointer")
# (unit, user policy, whether an object outside the display uses the unit's mesh)
UNITS = [
    ("object", "repoint", False),
    ("asset", "repoint", False),
    ("all", "repoint", False),
    ("mesh", "repoint", False),
    ("mesh", "replace", False),
    ("mesh", "repoint", True),
    ("mesh", "replace", True),
]
# The stress fixture binds no materials.
MATERIALS = [("material", "repoint", False), ("material", "replace", False)]
CASES = [("appearance", *u) for u in UNITS + MATERIALS] + [("stress", *u) for u in UNITS]


@pytest.fixture
def scene(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[Path]:
    if request.param == "appearance":
        with appearance.appearance_cases(tmp_path) as cases:
            yield cases.root
    else:
        with appearance.nested_stress(tmp_path) as stress:
            yield stress.root


@pytest.mark.parametrize(
    ("scene", "unit", "users", "unmanaged"), CASES, ids=["-".join(map(str, c)) for c in CASES], indirect=["scene"]
)
def test_replacement_changes_only_its_unit(
    scene: Path, wheel: Runtime, hydra_bridge: Path, tmp_path: Path, unit: str, users: str, unmanaged: bool
) -> None:
    result = _replace(scene, wheel, hydra_bridge, tmp_path, unit, users, unmanaged)
    before, after = result["before"], result["after"]
    assert result["prepared_untouched"]
    # The same display: every object's values, its mesh by plan index, and each slot's material.
    assert [_values(o) for o in after["objects"]] == [_values(o) for o in before["objects"]]
    # The published objects and their shear parents, nothing else, from publication on.
    assert result["linked"] == {"published": after["linked"], "retired": after["linked"]}

    named = result["unit"]
    meshes, materials = set(named["meshes"]), set(named["materials"])
    using = {
        index
        for index, record in enumerate(result["plan"])
        if record["mesh"] in meshes or materials.intersection(record["material_slots"])
    }
    replaced = set(named["objects"]) | (using if users == "replace" else set())
    assert replaced or meshes or materials, "the case names nothing to replace"
    for kind, changed in (("meshes", meshes), ("materials", materials)):
        for index, (old, new) in enumerate(zip(before[kind], after[kind], strict=True)):
            assert (old != new) == (index in changed), (kind, index)
    for index, (old, new) in enumerate(zip(before["objects"], after["objects"], strict=True)):
        assert (old["pointer"] != new["pointer"]) == (index in replaced), index
        mesh = result["plan"][index]["mesh"]
        if mesh is not None:  # a kept object is on the replacement of its mesh
            assert new["data_pointer"] == after["meshes"][mesh], index

    counts = result["counts"]
    outside = result["unmanaged"]
    if outside is None:
        assert counts["after"] == counts["before"]  # nothing left over, the staging collection included
        assert result["kept"] == []
    else:
        # OWN-08: the old mesh stays, unchanged, for the object outside the display.
        (old,) = (before["meshes"][index] for index in meshes)
        assert outside["data"] == old
        assert outside["positions_kept"]
        assert result["kept"] == [old]
        assert counts["after"] == {**counts["before"], "meshes": counts["before"]["meshes"] + 1}


def _replace(
    scene: Path, wheel: Runtime, hydra_bridge: Path, tmp_path: Path, unit: str, users: str, unmanaged: bool
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"scene": str(scene), "unit": unit, "users": users, "unmanaged": unmanaged}
    return run_isolated(wheel, BODY, "replace_unit", tmp_path, module_dir=str(hydra_bridge), **kwargs)


def _values(held: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in held.items() if key not in POINTERS}


DIFF_BODY = Path(__file__).parent / "bodies/plan_diff.py"
APPEARANCE_EDITS = ["unchanged", "transform", "shared-geometry", "material", "primvar", "visibility", "structure"]
APPEARANCE_EDITS += ["instance-transform", "instance-remove", "instance-remove-another", "instance-restore"]
APPEARANCE_EDITS += ["instance-color"]


@pytest.mark.parametrize("representation", ["objects", "batched"])
@pytest.mark.parametrize("users", ["repoint", "replace"])
@pytest.mark.parametrize("fixture", ["appearance", "universe", "stress"])
def test_update_follows_edits(
    fixture: str, users: str, representation: str, wheel: Runtime, hydra_bridge: Path, tmp_path: Path
) -> None:
    """C2 and D4: after each edit, the display updated by the plan diff holds what a fresh application does.

    On both representations: the baseline (update.py) and the batched display (batch_update.py).
    """
    generators = {
        "appearance": (appearance.appearance_cases, APPEARANCE_EDITS),
        "universe": (interaction.universe_membership, ["unchanged", "unload", "load"]),
        "stress": (appearance.nested_stress, ["unchanged"]),
    }
    generator, edits = generators[fixture]
    with generator(tmp_path / "scene") as built:
        kwargs: dict[str, Any] = {"module_dir": str(hydra_bridge), "scene": str(built.root), "edits": edits}
        kwargs |= {"users": users, "representation": representation}
        steps = run_isolated(wheel, DIFF_BODY, "update_edits", tmp_path, **kwargs)
    for step in steps:
        edit, diff, before, after = step["edit"], step["diff"], step["before"], step["after"]
        assert step["held"] == step["fresh"], edit
        assert step["counts"] == step["fresh_counts"], edit  # nothing left over
        # From publication on, the collection links exactly the published display.
        assert step["linked"]["published"] == step["linked"]["expected"], edit
        for kind in ("meshes", "materials"):
            for index, old in enumerate(diff[kind]):
                kept = old != -1 and after[kind][index] == before[kind][old]
                assert kept == (old != -1), (edit, kind, index)
        rebuilt = set(diff["changed"]) - (set(diff["repointable"]) if users == "repoint" else set())
        if representation == "objects":
            assert step["elements"] == list(range(len(after["objects"]))), edit  # each object names its plan index
            kept = _kept_objects(diff, before, after, rebuilt, edit)
        else:
            assert step["elements"] == [i for i, p in enumerate(after["objects"]) if p is not None], edit
            kept = _kept_objects(diff, before, after, rebuilt, edit) | _kept_instances(diff, before, after, edit)
        # Every element was selected before the edit, and only those the update kept still are, in the viewport.
        assert step["selected"] == sorted(i for i in kept if step["held"][i]["viewport"]), edit
        if edit == "unchanged":
            nothing = {"created": 0, "repointed": 0, "renumbered": 0, "retired": 0, "staged": False}
            if representation == "batched":
                nothing |= {"added": 0, "dropped": 0, "points": 0, "reprototyped": 0, "renumbered batches": 0}
            assert step["written"] == nothing


def _kept_objects(
    diff: dict[str, Any], before: dict[str, Any], after: dict[str, Any], rebuilt: set[int], edit: str
) -> set[int]:
    """Check that the display keeps exactly the objects the diff keeps; returns their new plan indices.

    A batched display's objects are those it keeps as objects, and an instance's pointer is None.
    """
    previous = {p for p in before["objects"] if p is not None}
    kept = set()
    for index, old in enumerate(diff["objects"]):
        new = after["objects"][index]
        if new is None:
            continue
        if old == -1 or index in rebuilt or before["objects"][old] is None:
            assert new not in previous, (edit, index)
        else:
            assert new == before["objects"][old], (edit, index)
            kept.add(index)
    return kept


def _kept_instances(diff: dict[str, Any], before: dict[str, Any], after: dict[str, Any], edit: str) -> set[int]:
    """Check what an update kept of each batch; returns the new plan indices of the instances it kept.

    A batch that keeps its prototype keeps its carriers, and also its points unless a member changed other than
    in its mesh or materials, or its members did. Its members kept from the old batch are the kept instances.
    """
    moved = set(diff["changed"]) - set(diff["repointable"])
    old_batches = {batch["prototype"]: batch for batch in before["batches"]}
    previous = {p for batch in before["batches"] for p in [*batch["carriers"], batch["prototype"], batch["points"]]}
    kept = set()
    for batch in after["batches"]:
        old = old_batches.get(batch["prototype"])
        if old is None:
            assert previous.isdisjoint([*batch["carriers"], batch["points"]]), (edit, batch)
            continue
        assert batch["carriers"] == old["carriers"], (edit, batch)
        olds = [diff["objects"][index] for index in batch["elements"]]
        unchanged = olds == old["elements"] and moved.isdisjoint(batch["elements"])
        assert (batch["points"] == old["points"]) == unchanged, (edit, batch)
        kept |= {i for i, o in zip(batch["elements"], olds, strict=True) if o in old["elements"] and i not in moved}
    # A batch whose members are all unchanged, and were exactly one old batch's, is kept whole.
    for old in before["batches"]:
        news = [index for index, o in enumerate(diff["objects"]) if o in old["elements"]]
        if [diff["objects"][index] for index in news] == old["elements"] and moved.isdisjoint(news):
            assert any(batch["points"] == old["points"] for batch in after["batches"]), (edit, old)
    return kept
