"""Run clang-tidy on the repository's C++ with the compile commands of each build (a pre-commit hook).

Two projects: the compiled core (src/proscenium/core/) and M1b's Hydra bridge (tools/feasibility/hydra_bridge/),
which M4's prototypes extend. It configures each one's CMake build directory (tools/native_build.py), so
clang-tidy parses each source with the flags and Blender headers that build uses. The first run fetches those
headers (tools/blender_deps.py). clang-tidy finds the checks itself, in the repository's root .clang-tidy.
"""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import native_build
from blender_deps import Platform, current_platform

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "proscenium" / "core"


@dataclass(frozen=True)
class TidyProject:
    """A CMake project whose sources clang-tidy checks."""

    sources: Path  # the CMake project, whose *.cpp files (or src/*.cpp) are checked
    results: Path  # its build's results directory; the CMake directory is beside it

    def files(self) -> list[Path]:
        """The project's C++ sources, at its top level and in src/."""
        return sorted([*self.sources.glob("*.cpp"), *self.sources.glob("src/*.cpp")])


PROJECTS = (
    TidyProject(CORE, ROOT / "build" / "core"),  # build_extension.py's results directory for the core
    TidyProject(ROOT / "tools" / "feasibility" / "hydra_bridge", ROOT / "build" / "hydra-bridge"),  # build.py's
)


def main() -> int:
    """Run clang-tidy on each project's sources; the exit status, nonzero if any project's run failed."""
    key = current_platform()
    status = 0
    for project in PROJECTS:
        build = native_build.cmake_dir(project.results)
        native_build.configure(project.sources, build)
        command = [
            native_build.tool("clang-tidy"),
            "-p",
            str(build),
            "--quiet",
            # The project's own headers; USD's and the standard library's are never reported.
            f"--header-filter={project.sources.as_posix()}/",
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
            codes = list(pool.map(tidy, project.files()))
        status = status or max(codes, default=0)
    return status


if __name__ == "__main__":
    sys.exit(main())
