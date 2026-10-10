"""The production-like CI fixture composes its derived inventory and is deterministic."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pxr import Usd

from fixtures import production_like
from fixtures.production_like import Params

if TYPE_CHECKING:
    from pathlib import Path

# SHA-256 of the default fixture. Update it deliberately when the generator or its
# assets change; an unexpected change means the fixture is no longer what tests assume.
# CI checks the same value on every platform.
DEFAULT_CHECKSUM = "ae6c3245c9215e16a861473876f6e8448450f2da3711e078df239e1c229da3bc"

POLICIES = {"load-all": Usd.Stage.LoadAll, "load-none": Usd.Stage.LoadNone}
PARAMS = [
    Params(),
    Params(fanout=(3, 1, 2, 2), levels=1, crates_per_bay=1),
    Params(fanout=(), levels=0, crates_per_bay=1),  # smallest: one crate directly under /World
]


@pytest.mark.parametrize("params", PARAMS, ids=str)
@pytest.mark.parametrize("policy", list(POLICIES))
def test_inventory_matches_parameters(params: Params, policy: str, tmp_path: Path) -> None:
    root = production_like.generate(tmp_path, params)
    stage = Usd.Stage.Open(str(root), POLICIES[policy])
    assert production_like.inventory(stage) == production_like.expected_inventory(params, policy == "load-all")


@pytest.mark.parametrize(
    "kwargs", [{"crates_per_bay": 0}, {"fanout": (2, 0)}, {"levels": -1}, {"fanout": (1,) * 6}], ids=str
)
def test_params_outside_the_inventory_formula_are_rejected(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Params(**kwargs)


def test_inventory_rejects_two_prototypes_for_one_asset(tmp_path: Path) -> None:
    stage = Usd.Stage.Open(str(production_like.generate(tmp_path)))
    # An extra arc on one crate gives it a prototype of its own.
    crate = stage.GetPrimAtPath("/World/Site_0/Area_0/Bay_0/Level_0/Level_1/Level_2/Crate_0")
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        crate.GetReferences().AddReference(str(tmp_path / "assets" / "ground.usda"))
    with pytest.raises(AssertionError, match="more than one prototype for asset 'crate'"):
        production_like.inventory(stage)


def test_generation_is_deterministic(tmp_path: Path) -> None:
    production_like.generate(tmp_path / "a")
    production_like.generate(tmp_path / "b")
    assert production_like.checksum(tmp_path / "a") == production_like.checksum(tmp_path / "b")


def test_default_fixture_checksum(tmp_path: Path) -> None:
    production_like.generate(tmp_path)
    assert production_like.checksum(tmp_path) == DEFAULT_CHECKSUM
