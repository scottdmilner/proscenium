"""The CI fixture opens in Blender's own pxr, in the wheel and the binary (cross-platform smoke)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fixtures import production_like
from fixtures.production_like import Params

from .harness import Runtime, run_isolated

BODIES = Path(__file__).parent / "bodies"


@pytest.mark.parametrize("load_all", [True, False], ids=["load-all", "load-none"])
def test_ci_fixture_inventory(runtime: Runtime, load_all: bool, tmp_path: Path) -> None:
    root = production_like.generate(tmp_path)
    result = run_isolated(runtime, BODIES / "ci_fixture.py", "inventory", tmp_path, root=str(root), load_all=load_all)
    assert result == production_like.expected_inventory(Params(), load_all)
