"""Save/reopen in a fresh process, in the wheel and the binary (cross-platform smoke)."""

from __future__ import annotations

from pathlib import Path

from .harness import Runtime, run_isolated

BODIES = Path(__file__).parent / "bodies"


def test_save_and_reopen_with_handlers(runtime: Runtime, tmp_path: Path) -> None:
    blend = tmp_path / "roundtrip.blend"
    result = run_isolated(runtime, BODIES / "roundtrip.py", "save_and_reopen_with_handlers", tmp_path, path=str(blend))
    assert result["objects"] == ["Kept"]
    assert Path(result["filepath"]) == blend
    # The reopen is one real file load: the persistent handler fires once; the
    # transient one is removed before load_post runs (runtime-record.md#handlers).
    assert result["load_post_calls"] == {"persistent": 1, "transient": 0}
    assert result["persistent_still_registered"]
    assert not result["transient_still_registered"]
