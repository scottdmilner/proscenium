"""Cache exact Blender headers (and Windows import libraries); warm builds need no Git network access.

Prints the dependency directory on stdout for CMake; progress goes to stderr.
The Blender release comes from uv.lock's bpy version (tools/blender_release.py). Its git tag
records each precompiled-library repo's revision as a submodule under lib/; those are the pins.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from blender_release import blender_tag, blender_version  # noqa: E402

BLENDER_URL = "https://projects.blender.org/blender/blender.git"


class Platform(StrEnum):
    """The supported platforms, by Blender's extension platform identifiers."""

    MACOS_ARM64 = "macos-arm64"
    LINUX_X64 = "linux-x64"
    WINDOWS_X64 = "windows-x64"


@dataclass(frozen=True)
class Libs:
    repo: str  # projects.blender.org/blender/<repo>; the Blender repo's submodule is lib/<suffix>
    paths: tuple[str, ...]  # non-cone sparse-checkout patterns
    required: tuple[str, ...]  # files that must exist after checkout

    @property
    def submodule(self) -> str:
        return "lib/" + self.repo.removeprefix("lib-")


LIBS = {
    Platform.MACOS_ARM64: Libs(
        "lib-macos_arm64",
        ("/usd/include/", "/tbb/include/", "/python/include/"),
        ("usd/include/pxr/pxr.h", "tbb/include/tbb/tbb.h", "python/include/python3.13/Python.h"),
    ),
    Platform.LINUX_X64: Libs(
        "lib-linux_x64",
        ("/usd/include/", "/tbb/include/", "/python/include/"),
        ("usd/include/pxr/pxr.h", "tbb/include/tbb/tbb.h", "python/include/python3.13/Python.h"),
    ),
    # Windows links through import libraries, which only the lib repo has (not the bpy wheel).
    Platform.WINDOWS_X64: Libs(
        "lib-windows_x64",
        (
            "/usd/include/",
            "/usd/lib/usd_ms.lib",
            "/tbb/include/",
            "/tbb/lib/tbb12.lib",
            "/python/313/include/",
            "/python/313/libs/python313.lib",
        ),
        (
            "usd/include/pxr/pxr.h",
            "usd/lib/usd_ms.lib",
            "tbb/include/tbb/tbb.h",
            "tbb/lib/tbb12.lib",
            "python/313/include/Python.h",
            "python/313/libs/python313.lib",
        ),
    ),
}


def current_platform() -> Platform:
    """This machine's platform, limited to the supported three."""
    system, machine = platform.system(), platform.machine().lower()
    key = {
        ("Darwin", "arm64"): Platform.MACOS_ARM64,
        ("Linux", "x86_64"): Platform.LINUX_X64,
        ("Windows", "amd64"): Platform.WINDOWS_X64,
    }.get((system, machine))
    if key is None:
        raise RuntimeError(f"Unsupported platform for the Hydra bridge: {system} {machine}")
    return key


def release() -> dict[str, str]:
    """The locked Blender release: its tag, commit, and lib/ submodule revisions; cached per tag."""
    tag = blender_tag()
    cache = HERE / "external" / f"blender-{tag}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    _log(f"Resolving Blender {tag} library revisions from {BLENDER_URL}")
    with tempfile.TemporaryDirectory(prefix="blender-tag-") as tmp:
        # Treeless and shallow: only the commit and the trees on the way to lib/ are fetched.
        _git(
            None, "clone", "--quiet", "--filter=tree:0", "--no-checkout", "--depth=1", "--branch", tag, BLENDER_URL, tmp
        )
        commit = _output(tmp, "rev-parse", "HEAD")
        entries = _output(tmp, "ls-tree", "HEAD", "lib/").splitlines()
    # "<mode> commit <sha>\t<path>" for each submodule.
    submodules = {line.split("\t")[1]: line.split()[2] for line in entries if line.split()[1] == "commit"}
    resolved = {"tag": tag, "commit": commit, **{libs.submodule: submodules[libs.submodule] for libs in LIBS.values()}}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(resolved, indent=2) + "\n", encoding="utf-8")
    return resolved


def deps_dir(key: Platform) -> Path:
    return HERE / "external" / LIBS[key].repo


def prepare(key: Platform) -> Path:
    libs = LIBS[key]
    revision = release()[libs.submodule]
    deps = deps_dir(key)
    url = f"https://projects.blender.org/blender/{libs.repo}.git"
    if not deps.exists():
        deps.parent.mkdir(parents=True, exist_ok=True)
        major, minor = blender_version().split(".")[:2]
        branch = f"blender-v{major}.{minor}-release"
        _git(None, "clone", "--filter=blob:none", "--no-checkout", "--depth=1", "--branch", branch, url, str(deps))
    head = _output(deps, "rev-parse", "HEAD")
    # Never overwrite local changes to repair or switch a cached checkout.
    dirty = _output(deps, "diff", "--name-only", "HEAD")
    # A fresh --no-checkout clone has no index and reports every file deleted.
    if (deps / ".git/index").exists() and dirty:
        raise RuntimeError(f"Dependency checkout has local changes: {deps}")
    if head == revision and all((deps / f).is_file() for f in libs.required):
        _log(f"Using cached Blender dependencies: {deps} ({revision})")
        return deps
    present = subprocess.run(
        ["git", "-C", str(deps), "cat-file", "-e", f"{revision}^{{commit}}"], capture_output=True, check=False
    )
    if present.returncode:
        _git(deps, "fetch", "--depth=1", "origin", revision)
    _git(deps, "sparse-checkout", "set", "--no-cone", *libs.paths)
    _git(deps, "checkout", "--detach", revision)
    missing = [f for f in libs.required if not (deps / f).is_file()]
    if missing:
        raise RuntimeError(f"Expected dependency files are missing from {deps}: {missing}")
    return deps


def _git(cwd: Path | None, *args: str) -> None:
    command = ["git", *(["-C", str(cwd)] if cwd else []), *args]
    # Git progress goes to stderr; keep stdout for the directory CMake reads.
    subprocess.run(command, check=True, stdout=sys.stderr)


def _output(cwd: str | Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


if __name__ == "__main__":
    print(prepare(current_platform()))
