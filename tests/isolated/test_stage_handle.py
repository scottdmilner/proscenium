"""The core never keeps a released stage alive, and never destroys one its caller holds (AGENTS.md "Compiled core").

Native stage lifetimes run in a fresh process, since a mistake here is a use-after-free. The
caller-drop case is the core's part of MEM-05: once released, a stage the caller dropped expires.
"""

from __future__ import annotations

from pathlib import Path

from .harness import Runtime, run_isolated

BODIES = Path(__file__).parent / "bodies"


def test_released_handle_lets_a_dropped_stage_expire(wheel: Runtime, tmp_path: Path) -> None:
    result = run_isolated(wheel, BODIES / "stage_handle.py", "caller_drops_then_release", tmp_path)
    assert result == {
        "is_callers_stage": True,
        "alive_while_held": True,  # the handle's own reference
        "expired_after_release": True,
        "stage_after_release": False,
        "released": True,
    }


def test_release_leaves_a_caller_held_stage_alive(wheel: Runtime, tmp_path: Path) -> None:
    result = run_isolated(wheel, BODIES / "stage_handle.py", "release_while_caller_holds", tmp_path)
    assert result == {"stage_after_release": True, "caller_stage_valid": True}
