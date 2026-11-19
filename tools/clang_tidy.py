"""Run clang-tidy on the repository's C++ with the compile commands of each build (a pre-commit hook).

Three projects, which tools/native_build.py names: the planner (proscenium_sync's planner/), the cook
(proscenium_cook's tree_cook/), and M1b's Hydra bridge (tools/feasibility/hydra_bridge/), which M4's prototypes
extend. It configures each one's CMake build directory, so
clang-tidy parses each source with the flags and Blender headers that build uses. The first run fetches those headers
(tools/blender_deps.py). clang-tidy finds the checks itself, in the repository's root .clang-tidy.
"""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import native_build
from blender_deps import Platform, current_platform

if TYPE_CHECKING:
    from pathlib import Path


def _sources(module: native_build.NativeModule) -> list[Path]:
    """The project's C++ sources: top level and one directory down (the bridge's src/, the planner's inspection/)."""
    return sorted([*module.source_dir.glob("*.cpp"), *module.source_dir.glob("*/*.cpp")])


def main() -> int:
    """Run clang-tidy on each project's sources; the exit status, nonzero if any project's run failed."""
    key = current_platform()
    status = 0
    for module in (native_build.PLANNER, native_build.COOK, native_build.HYDRA_BRIDGE):
        native_build.configure(module)
        command = [
            native_build.tool("clang-tidy"),
            "-p",
            str(module.cmake_dir),
            "--quiet",
            # The project's own headers; USD's and the standard library's are never reported.
            f"--header-filter={module.source_dir.as_posix()}/",
        ]
        if key == Platform.MACOS_ARM64:
            # AppleClang's compile commands leave the SDK implicit; clang-tidy's own clang needs it named.
            sdk = subprocess.run(["xcrun", "--show-sdk-path"], check=True, capture_output=True, text=True)
            command.append(f"--extra-arg=-isysroot{sdk.stdout.strip()}")
        env = native_build.build_env(key)

        # One clang-tidy per source, in parallel; each prints its findings once it finishes.
        def tidy(path: Path, command: list[str] = command, env: dict[str, str] = env) -> int:
            result = subprocess.run([*command, str(path)], check=False, env=env, capture_output=True, text=True)
            sys.stdout.write(result.stdout + result.stderr)
            return result.returncode

        with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
            codes = list(pool.map(tidy, _sources(module)))
        status = status or max(codes, default=0)
    return status


if __name__ == "__main__":
    sys.exit(main())
