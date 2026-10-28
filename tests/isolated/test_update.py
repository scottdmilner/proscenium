"""M4's small updates in the object baseline (M04-prototypes plan, B6): replacing one unit of a published display.

The bridge's update.py prepares a unit beside the display, publishes it, and retires what it replaced. Each case
replaces the unit from the same plan, so the display must hold what it held before, with new data exactly where
the unit and its user policy say, and nothing left over.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from fixtures import appearance

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
