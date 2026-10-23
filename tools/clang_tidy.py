"""Run clang-tidy on the compiled core's sources with the compile commands of its build (a pre-commit hook).

It configures the core's CMake build directory (tools/native_build.py), so clang-tidy
parses each source with the flags and Blender headers the build uses. The first run
fetches those headers (tools/blender_deps.py). Checks are in src/proscenium/core/.clang-tidy.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import native_build
from blender_deps import Platform, current_platform

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "proscenium" / "core"
BUILD = ROOT / "build" / "core"  # build_extension.py's results directory for the core


def main() -> int:
    """Run clang-tidy on the compiled core's sources; the exit status."""
    key = current_platform()
    build = native_build.cmake_dir(BUILD)
    native_build.configure(CORE, build)
    command = [native_build.tool("clang-tidy"), "-p", str(build), "--quiet"]
    if key == Platform.MACOS_ARM64:
        # AppleClang's compile commands leave the SDK implicit; clang-tidy's own clang needs it named.
        sdk = subprocess.run(["xcrun", "--show-sdk-path"], check=True, capture_output=True, text=True).stdout.strip()
        command.append(f"--extra-arg=-isysroot{sdk}")
    sources = sorted(str(path) for path in CORE.glob("*.cpp"))
    return subprocess.run([*command, *sources], check=False, env=native_build.build_env(key)).returncode


if __name__ == "__main__":
    sys.exit(main())
