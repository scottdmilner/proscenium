"""An attachment never keeps the caller's stage alive (SRC-02).

Native stage lifetimes run in a fresh process, since a mistake here is a use-after-free.
"""

from __future__ import annotations

from pathlib import Path

from .harness import Runtime, run_isolated

BODIES = Path(__file__).parent / "bodies"


def test_caller_releasing_its_stage_leaves_the_binding_unattached(wheel: Runtime, tmp_path: Path) -> None:
    result = run_isolated(
        wheel, BODIES / "attachments.py", "caller_releases_its_stage", tmp_path, tmp_dir=str(tmp_path)
    )
    assert result == {
        "attached_before": True,
        "attached_after": False,
        "acquire": "unavailable",
        "session_layer_freed": True,
    }
