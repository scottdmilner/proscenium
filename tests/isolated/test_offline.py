"""F-OFFLINE's saved display without the extension (lifecycle.md#schema-versions), in the wheel and the binary."""

from __future__ import annotations

from pathlib import Path

from fixtures.source_access import DISPLAY
from support.display import expected_content

from .harness import WHEEL, Runtime, run_isolated

BODIES = Path(__file__).parent / "bodies"


def test_saved_display_without_the_extension(runtime: Runtime, tmp_path: Path) -> None:
    # SCHEMA-05, F-OFFLINE "no-extension": published and saved with the extension, opened in a process
    # that never imports it, where its geometry, transforms, and materials are ordinary Blender data.
    blend = tmp_path / "offline.blend"
    saved = run_isolated(
        WHEEL, BODIES / "offline.py", "publish_and_save", tmp_path, tmp_dir=str(tmp_path), path=str(blend)
    )
    assert saved == expected_content(DISPLAY)
    opened = run_isolated(runtime, BODIES / "offline.py", "open_without_extension", tmp_path, path=str(blend))
    assert opened == {"loaded": ["FINISHED"], "extension_imported": False, "content": saved}
