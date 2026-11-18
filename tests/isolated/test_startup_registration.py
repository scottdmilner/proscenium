"""The installed extension registers without a traceback when Blender, opening its window, enables it at startup.

At startup, Blender enables the add-ons its preferences name before it loads a file, with bpy.data restricted, which
neither the bpy wheel nor background mode reaches. The isolated harness starts from --factory-startup, which ignores the
preferences, so this test starts Blender itself: it installs the zip as tools/launch_blender.py does, enabled in a user
dir of its own, then opens a window on that dir, which runs the extension's startup registration, and quits.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from launch_blender import install, isolated_env

if TYPE_CHECKING:
    from pathlib import Path

    from .harness import Runtime

# The extension's registration and everything it registers, and the install the test shares with the launcher. A local
# run skips this test until one of these changes (windowed_runs.py).
pytestmark = pytest.mark.windowed(
    covers=(
        "src/proscenium/",
        "packages/proscenium_sync/src/proscenium_sync/",
        "packages/proscenium_ui/src/proscenium_ui/",
        "tools/launch_blender.py",
    )
)
MODULE = "bl_ext.user_default.proscenium"
# Runs after startup has enabled the add-ons and loaded the startup file; reports whether the extension stayed enabled,
# then quits from the window's event loop.
REPORT_AND_QUIT = f"""
import bpy
print("PROSCENIUM_ENABLED", {MODULE!r} in bpy.context.preferences.addons)
bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender(), first_interval=1.0)
"""
TIMEOUT_SECONDS = 120  # a window that never draws times out


def test_startup_registration_prints_no_traceback(
    windowed_binary: Runtime, extension_zip: Path, tmp_path: Path
) -> None:
    blender = windowed_binary.blender_executable
    assert blender is not None  # a binary runtime's
    env = isolated_env(tmp_path / "user")
    install(blender, extension_zip, env)
    # Without --factory-startup, so the preferences that enable the extension load. A window ignores the real mouse and
    # keyboard with --enable-event-simulate, as the harness's windowed runs do.
    command = [blender, "--enable-event-simulate", "--python-exit-code", "1", "--python-expr", REPORT_AND_QUIT]
    proc = subprocess.run(command, env=env, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False)
    log = proc.stdout + proc.stderr
    assert "Traceback" not in log, log
    assert "PROSCENIUM_ENABLED True" in log, log
    assert proc.returncode == 0, log
