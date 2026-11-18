"""Locate the Blender binary and the extension CLI shipped inside the bpy wheel."""

from __future__ import annotations

import importlib.util
import os
import platform
import plistlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_BLENDER = {
    "Darwin": ["/Applications/Blender.app/Contents/MacOS/Blender"],
    "Linux": ["blender"],
    "Windows": [r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe", "blender.exe"],
}
VERSION_LINE = re.compile(r"^Blender (\d+)\.(\d+)\.(\d+)", re.MULTILINE)

type Version = tuple[int, int, int]


def find_blender() -> str | None:
    """The BLENDER env var, else a platform default; None if neither exists."""
    for candidate in [os.environ.get("BLENDER"), *DEFAULT_BLENDER.get(platform.system(), [])]:
        if candidate and (shutil.which(candidate) or Path(candidate).exists()):
            return shutil.which(candidate) or candidate
    return None


def blender_candidates() -> list[str]:
    """Every Blender binary found: the BLENDER env var, PATH, then the platform's usual install locations."""
    home = Path.home()
    match platform.system():
        case "Darwin":
            installs = [
                d.glob("Blender*.app/Contents/MacOS/Blender") for d in (Path("/Applications"), home / "Applications")
            ]
        case "Windows":
            program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            installs = [(program_files / "Blender Foundation").glob("Blender*/blender.exe")]
        case _:
            # Blender's Linux downloads are tarballs, usually unpacked into /opt or the home dir.
            installs = [d.glob("blender*/blender") for d in (Path("/opt"), home)]
    # Every blender or blender.exe on PATH, not only the first, so a later one of the right release is still found.
    on_path = [Path(d) / name for d in os.get_exec_path() for name in ("blender", "blender.exe")]
    env_blender = os.environ.get("BLENDER")
    names = [
        env_blender and (shutil.which(env_blender) or env_blender),
        *(str(p) for p in on_path if os.access(p, os.X_OK)),
        *(str(p) for found in installs for p in sorted(found)),
    ]
    candidates: list[str] = []
    seen: set[Path] = set()  # resolved, since a PATH entry is often a link to an install found below
    for name in names:
        if name and Path(name).is_file() and (resolved := Path(name).resolve()) not in seen:
            seen.add(resolved)
            candidates.append(name)
    return candidates


def blender_version(executable: str) -> Version | None:
    """The Blender release of `executable`, or None if it can't be read."""
    # A macOS bundle states its version in Info.plist, so other releases installed beside it are ruled out unstarted.
    plist = Path(executable).resolve().parents[1] / "Info.plist"
    if platform.system() == "Darwin" and plist.is_file():
        with plist.open("rb") as f:
            text = f"Blender {plistlib.load(f).get('CFBundleShortVersionString', '')}"
    else:
        try:
            text = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, timeout=60, check=False
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return None
    match = VERSION_LINE.search(text)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def pick_release(installed: Sequence[tuple[str, Version | None]], release: Version) -> str | None:
    """The first of `installed` that is exactly `release`, else the newest of its minor version; None without one."""
    same_minor = [(version, exe) for exe, version in installed if version and version[:2] == release[:2]]
    exact = [exe for version, exe in same_minor if version == release]
    if exact:
        return exact[0]
    return max(same_minor)[1] if same_minor else None


def wheel_extension_cli() -> Path | None:
    """blender_ext.py from the bpy wheel, found without importing bpy.

    It only needs the standard library, so any Python 3.13 can run it
    (see docs/feasibility/runtime-record.md#packaging).
    """
    spec = importlib.util.find_spec("bpy")
    if spec is None or spec.origin is None:
        return None
    matches = sorted(Path(spec.origin).parent.glob("*/scripts/addons_core/bl_pkg/cli/blender_ext.py"))
    return matches[-1] if matches else None
