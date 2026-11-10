"""The headless interaction functions (M04-prototypes plan, B3 and D3), by the reusable checks.

Each check in support/interaction_checks.py runs on each M2 interaction fixture in a fresh wheel process, with
the bridge's C++ correspondence and kind promotion and a Python display component: the baseline's
(object_display_selection.py)
and the batched display's (batched_display_object_display_selection.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from support.interaction_checks import CHECKS

from .harness import Runtime, run_isolated

BODY = Path(__file__).parent / "bodies/interaction.py"


@pytest.mark.parametrize("check", list(CHECKS))
@pytest.mark.parametrize("fixture", ["kind_hierarchy", "nested_selection", "universe_membership"])
@pytest.mark.parametrize("representation", ["objects", "batched"])
def test_interaction(  # noqa: PLR0913 - pytest's parameters and fixtures
    representation: str, fixture: str, check: str, wheel: Runtime, hydra_bridge: Path, tmp_path: Path
) -> None:
    kwargs: dict[str, Any] = {"module_dir": str(hydra_bridge), "fixture": fixture, "check": check}
    kwargs |= {"dest": str(tmp_path / "scene"), "representation": representation}
    result = run_isolated(wheel, BODY, "run_check", tmp_path, **kwargs)
    if result == "not applicable":
        pytest.skip(f"{fixture} has no case for {check}")
    assert result == "passed"


def test_select_tool_session(wheel: Runtime, hydra_bridge: Path, tmp_path: Path) -> None:
    # The source selection tool (select_tool.py, F2's Q4), headless: picks by what a ray cast returns, the modes,
    # a box's element centers, and following Blender's own selection.
    kwargs: dict[str, Any] = {"module_dir": str(hydra_bridge), "dest": str(tmp_path / "scene")}
    assert run_isolated(wheel, BODY, "select_tool_session", tmp_path, **kwargs) == []
