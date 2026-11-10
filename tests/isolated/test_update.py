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
APPEARANCE_EDITS = ["unchanged", "transform", "shared-geometry", "material", "primvar", "reshape", "visibility"]
APPEARANCE_EDITS += ["turn-and-show", "structure"]
APPEARANCE_EDITS += ["instance-transform", "kits-move", "purpose-move"]
APPEARANCE_EDITS += ["instance-remove", "instance-remove-another", "instance-restore"]
APPEARANCE_EDITS += ["instance-color", "color-interpolation", "uncolor", "merge-batches"]


@pytest.mark.parametrize("moves", [False, True])
@pytest.mark.parametrize("selection", ["all", "odd"])
@pytest.mark.parametrize("representation", ["objects", "batched"])
@pytest.mark.parametrize("users", ["repoint", "replace"])
@pytest.mark.parametrize("fixture", ["appearance", "universe", "stress"])
def test_update_follows_edits(  # noqa: PLR0913 - pytest's parameters and fixtures
    fixture: str,
    users: str,
    representation: str,
    selection: str,
    moves: bool,
    wheel: Runtime,
    hydra_bridge: Path,
    tmp_path: Path,
) -> None:
    """C2 and D4: after each edit, the display updated by the plan diff holds what a fresh application does.

    On both representations: the baseline (update.py) and the batched display (batch_update.py). Before each edit
    every element is selected, or on the appearance edits, those of odd plan index, so a batch holds two states.
    With moves (E2), updates keep moved objects and set their matrices.
    """
    if selection == "odd" and fixture != "appearance":
        pytest.skip("the appearance edits move some of a batch's copies")
    generators = {
        "appearance": (appearance.appearance_cases, APPEARANCE_EDITS),
        "universe": (interaction.universe_membership, ["unchanged", "unload", "load"]),
        "stress": (appearance.nested_stress, ["unchanged", "move-world"]),
    }
    generator, edits = generators[fixture]
    with generator(tmp_path / "scene") as built:
        kwargs: dict[str, Any] = {"module_dir": str(hydra_bridge), "scene": str(built.root), "edits": edits}
        kwargs |= {"users": users, "representation": representation, "select": selection, "moves": moves}
        steps = run_isolated(wheel, DIFF_BODY, "update_edits", tmp_path, **kwargs)
    _check_steps(steps, users, representation, selection, {edits.index("unchanged")}, moves)
    if fixture == "stress":
        # Moving every copy moves sheared ones, which keep their shear parents, so moves keep only the others.
        (step,) = (step for step in steps if step["edit"] == "move-world")
        kept = _kept_moves(step, users)
        assert set(step["diff"]["moved_object_indices"]) > kept


# M1b's animation case varies every kind of value its plan holds over [1, 3]; the repeated 3 changes nothing.
FRAMES = [1, 2, 3, 3, 1]


@pytest.mark.parametrize("moves", [False, True])
@pytest.mark.parametrize("users", ["repoint", "replace"])
@pytest.mark.parametrize("representation", ["objects", "batched"])
def test_update_follows_frames(  # noqa: PLR0913 - pytest's parameters and fixtures
    representation: str, users: str, moves: bool, wheel: Runtime, hydra_bridge: Path, tmp_path: Path
) -> None:
    """E2: per-time-code snapshots, stepped by a frame-change handler, hold what a fresh application does.

    On the bridge's frames.usda, each frame set after the first is synchronized through the update path, with
    every element selected before it, and checked as an edit is, under each user policy, with and without moves.
    """
    dest = tmp_path / "scene"
    dest.mkdir()
    kwargs: dict[str, Any] = {"module_dir": str(hydra_bridge), "dest": str(dest), "times": FRAMES}
    kwargs |= {"representation": representation, "users": users, "moves": moves}
    steps = run_isolated(wheel, DIFF_BODY, "frame_steps", tmp_path, **kwargs)
    assert [step["edit"] for step in steps] == [f"frame {frame}" for frame in FRAMES[1:]]
    repeat = FRAMES.index(3, FRAMES.index(3) + 1) - 1  # the step to frame 3 again
    for index, step in enumerate(steps):
        diff = step["diff"]
        changes = (
            diff["changed_object_indices"]
            or diff["removed_previous_object_indices"]
            or -1 in diff["previous_object_indices"]
        )
        assert bool(changes) == (index != repeat), step["edit"]
    _check_steps(steps, users, representation, "all", {repeat}, moves)
    if moves:
        # From 1 to 2 and 2 to 3, Comb, a placeholder, moves; so does Hand on its mesh, which it shares with the
        # Blades, so the batched display batches it; and Roam moves and changes its points, so it is kept and
        # repointed under repointing, and replaced under replacement.
        for step in steps[:2]:
            kept = {step["held"][index]["source"] for index in _kept_moves(step, users)}
            assert "/World/Comb" in kept, step["edit"]
            assert ("/World/Rig/Arm/Hand" in kept) == (representation == "objects"), step["edit"]
            assert ("/World/Roam" in kept) == (users == "repoint"), step["edit"]
        # Lean is sheared at 2, so it needs a shear parent there and is replaced; from 2 to 3 it has one throughout.
        lean = {step["held"][index]["source"] for step in steps[:2] for index in _kept_moves(step, users)}
        assert "/World/Lean" not in lean


def _check_steps(  # noqa: PLR0913 - the steps and how they were run
    steps: list[dict[str, Any]], users: str, representation: str, selection: str, unchanged: set[int], moves: bool
) -> None:
    """Each update's display against a fresh application, and what it kept, selected, and wrote.

    The steps at the positions `unchanged` names change nothing, so their updates must write nothing. With
    `moves`, the updates kept the moved objects _kept_moves names.
    """
    for position, step in enumerate(steps):
        edit, diff, before, after = step["edit"], step["diff"], step["before"], step["after"]
        assert step["held"] == step["fresh"], edit
        assert step["counts"] == _fresh_counts(step), edit  # nothing left over
        assert step["restored"] == [], edit  # no failure injected
        # From publication on, the collection links exactly the published display.
        assert step["linked"]["published"] == step["linked"]["expected"], edit
        for kind, previous_indices in (("meshes", "previous_mesh_indices"), ("materials", "previous_material_indices")):
            for index, old in enumerate(diff[previous_indices]):
                kept = old != -1 and after[kind][index] == before[kind][old]
                assert kept == (old != -1), (edit, kind, index)
        rebuilt = set(diff["changed_object_indices"]) - (
            set(diff["repointable_object_indices"]) if users == "repoint" else set()
        )
        if moves:
            rebuilt -= _kept_moves(step, users)
        if representation == "objects":
            assert step["elements"] == list(range(len(after["objects"]))), edit  # each object names its plan index
            kept = _kept_objects(diff, before, after, rebuilt, edit)
        else:
            assert step["elements"] == [i for i, p in enumerate(after["objects"]) if p is not None], edit
            kept = _kept_objects(diff, before, after, rebuilt, edit) | _kept_instances(diff, before, after, edit)
        # Of the elements selected before the edit, only those the update kept still are, in the viewport.
        was = {old for old in range(len(before["objects"])) if selection == "all" or old % 2}
        expected = sorted(i for i in kept if diff["previous_object_indices"][i] in was and step["held"][i]["viewport"])
        assert step["selected"] == expected, edit
        if position in unchanged:
            nothing = {"created": 0, "repointed": 0, "renumbered": 0, "retired": 0, "staged": False}
            if representation == "batched":
                nothing |= {"added": 0, "dropped": 0, "points": 0, "reprototyped": 0, "renumbered batches": 0}
            assert step["written"] == nothing


@pytest.mark.parametrize("moves", [False, True])
@pytest.mark.parametrize("representation", ["objects", "batched"])
@pytest.mark.parametrize("users", ["repoint", "replace"])
def test_failed_publication_restores_the_display(  # noqa: PLR0913 - pytest's parameters and fixtures
    users: str, representation: str, moves: bool, wheel: Runtime, hydra_bridge: Path, tmp_path: Path
) -> None:
    """B6 and D4: a publication that fails at any of its links or unlinks leaves the published display as it was.

    Each update's publication fails at each of its collection links and unlinks in turn, after every change it
    makes in place, then succeeds, and the display it publishes holds what a fresh application does. With moves,
    the changes in place include the moved objects' transforms.
    """
    with appearance.appearance_cases(tmp_path / "scene") as built:
        kwargs: dict[str, Any] = {"module_dir": str(hydra_bridge), "scene": str(built.root), "edits": APPEARANCE_EDITS}
        kwargs |= {"users": users, "representation": representation, "fail_publication": True, "moves": moves}
        steps = run_isolated(wheel, DIFF_BODY, "update_edits", tmp_path, **kwargs)
    for step in steps:
        edit = step["edit"]
        assert all(step["restored"]), (edit, step["restored"])
        assert len(step["restored"]) == step["operations"], edit  # one failure at each link and unlink
        assert step["held"] == step["fresh"], edit
        assert step["counts"] == _fresh_counts(step), edit
    assert sum(step["operations"] for step in steps) > len(steps)


def _kept_moves(step: dict[str, Any], users: str) -> set[int]:
    """The moved objects an update with moves keeps, by new plan index.

    Each is an object before and after, with a shear parent in neither display, and under replacement on the mesh
    it had. The fixtures change no moved object's materials.
    """
    diff, kept = step["diff"], set()
    for index in diff["moved_object_indices"]:
        was, now = step["before_values"][diff["previous_object_indices"][index]], step["held"][index]
        if was is None or step["after"]["objects"][index] is None:
            continue  # an instance of a batch, before or after
        if was["parent_world"] is not None or now["parent_world"] is not None:
            continue
        mesh = now["mesh_index"]
        same = was["mesh_index"] is None if mesh is None else diff["previous_mesh_indices"][mesh] == was["mesh_index"]
        if same or users == "repoint":
            kept.add(index)
    return kept


def _fresh_counts(step: dict[str, Any]) -> dict[str, int]:
    """What the updated display should hold, by kind: a fresh application's, with its selection's carriers.

    A fresh application selects nothing, so each batch has one carrier; the updated display keeps its members'
    selection, with a carrier for each state a batch's points hold (D3).
    """
    extra = sum(len(batch["carriers"]) - 1 for batch in step["after"]["batches"])
    return {**step["fresh_counts"], "objects": step["fresh_counts"]["objects"] + extra}


def _kept_objects(
    diff: dict[str, Any], before: dict[str, Any], after: dict[str, Any], rebuilt: set[int], edit: str
) -> set[int]:
    """Check that the display keeps exactly the objects the diff keeps; returns their new plan indices.

    A batched display's objects are those it keeps as objects, and an instance's pointer is None.
    """
    previous = {p for p in before["objects"] if p is not None}
    kept = set()
    for index, old in enumerate(diff["previous_object_indices"]):
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

    Every batch has a carrier for each state its points hold, and only those, selected exactly when the state is.
    A batch that keeps its prototype keeps its carriers of the states it still holds, gives a carrier of a state it
    no longer holds to one it newly holds, and creates one only for each state beyond those; it keeps its points
    unless a member changed other than in its mesh or materials, or its members did. Its members kept from the old
    batch are the kept instances.
    """
    moved = set(diff["changed_object_indices"]) - set(diff["repointable_object_indices"])
    old_batches = {batch["prototype"]: batch for batch in before["batches"]}
    previous = {
        p for batch in before["batches"] for p in [*batch["carriers"].values(), batch["prototype"], batch["points"]]
    }
    kept = set()
    for batch in after["batches"]:
        carriers = {int(state): pointer for state, pointer in batch["carriers"].items()}
        assert sorted(carriers) == batch["states"], (edit, batch)
        if batch["looks"][0]:  # Blender selects no object hidden in the viewport
            assert batch["selected_carriers"] == [state for state in batch["states"] if state != 0], (edit, batch)
        # Its carriers show in its destinations and are placed alike.
        assert len(batch["carrier_looks"]) == 1, (edit, batch)
        assert batch["carrier_looks"][0][:2] == batch["looks"][:2], (edit, batch)
        old = old_batches.get(batch["prototype"])
        if old is None:
            assert previous.isdisjoint([*carriers.values(), batch["points"]]), (edit, batch)
            continue
        before_carriers = {int(state): pointer for state, pointer in old["carriers"].items()}
        for state in carriers.keys() & before_carriers.keys():
            assert carriers[state] == before_carriers[state], (edit, batch)
        fresh = [pointer for pointer in carriers.values() if pointer not in before_carriers.values()]
        assert previous.isdisjoint(fresh), (edit, batch)
        assert len(fresh) == max(0, len(carriers) - len(before_carriers)), (edit, batch)
        olds = [diff["previous_object_indices"][index] for index in batch["elements"]]
        unchanged = olds == old["elements"] and moved.isdisjoint(batch["elements"])
        assert (batch["points"] == old["points"]) == unchanged, (edit, batch)
        kept |= {i for i, o in zip(batch["elements"], olds, strict=True) if o in old["elements"] and i not in moved}
    # Each group keeps the batch of the same looks that holds the most of its members' old counterparts, of those
    # no other group keeps: none of those left over holds more, nor any for a group with a new batch.
    claimed = {batch["prototype"] for batch in after["batches"]} & old_batches.keys()
    for batch in after["batches"]:
        olds = {diff["previous_object_indices"][index] for index in batch["elements"]}
        old = old_batches.get(batch["prototype"])
        most = 0 if old is None else len(olds.intersection(old["elements"]))
        for other in before["batches"]:
            if other["prototype"] not in claimed and other["looks"] == batch["looks"]:
                assert len(olds.intersection(other["elements"])) <= most, (edit, batch, other)
    # A batch whose members are all unchanged, and were exactly one old batch's, is kept whole.
    for batch in after["batches"]:
        olds = [diff["previous_object_indices"][index] for index in batch["elements"]]
        whole = [old for old in before["batches"] if old["elements"] == olds]
        if whole and moved.isdisjoint(batch["elements"]):
            assert batch["points"] == whole[0]["points"], (edit, batch)
    return kept
