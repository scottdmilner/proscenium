"""A binding holds its attached stage until the caller releases the attachment (SRC-02).

Native stage lifetimes run in a fresh process, since a mistake here is a use-after-free.
"""

from __future__ import annotations

from pathlib import Path

from .harness import Runtime, run_isolated

BODIES = Path(__file__).parent / "bodies"


def test_the_binding_holds_its_attached_stage_until_released(wheel: Runtime, tmp_path: Path) -> None:
    # Dropping the caller's references releases nothing: the stage and its unsaved edits stay loaded.
    # Releasing the attachment lets the stage expire and its layers go, and leaves the binding unattached.
    result = run_isolated(
        wheel, BODIES / "attachments.py", "caller_drops_then_releases", tmp_path, tmp_dir=str(tmp_path)
    )
    assert result == {
        "attached_after_drop": True,
        "edit_loaded_after_drop": True,
        "expired_after_release": True,
        "attached_after_release": False,
        "acquire": "unavailable",
        "session_layer_freed": True,
    }
