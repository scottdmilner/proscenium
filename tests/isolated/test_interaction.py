"""The baseline's headless interaction functions (M04-prototypes plan, B3), by the reusable checks.

Each check in support/interaction_checks.py runs on each M2 interaction fixture in a fresh wheel process, with
the bridge's C++ correspondence and kind promotion and the Python display component (selection.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from support.interaction_checks import CHECKS

from .harness import Runtime, run_isolated

BODY = Path(__file__).parent / "bodies/interaction.py"


@pytest.mark.parametrize("check", list(CHECKS))
@pytest.mark.parametrize("fixture", ["kind_hierarchy", "nested_selection", "universe_membership"])
def test_baseline_interaction(fixture: str, check: str, wheel: Runtime, hydra_bridge: Path, tmp_path: Path) -> None:
    dest = tmp_path / "scene"
    result = run_isolated(
        wheel, BODY, "run_check", tmp_path, module_dir=str(hydra_bridge), fixture=fixture, check=check, dest=str(dest)
    )
    if result == "not applicable":
        pytest.skip(f"{fixture} has no case for {check}")
    assert result == "passed"
