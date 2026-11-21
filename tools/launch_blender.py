"""Build the extension zip and start Blender with it installed and enabled, apart from the user's own Blender setup.

    uv run proscenium-blender [--blender PATH] [--fresh] [--no-build] [-- BLENDER_ARGS...]

1. Build dist/proscenium-<version>.zip as tools/build/build_extension.py does, which
   first syncs the source dir's wheels, manifest, and planner (--no-build: use
   the zip already there).
2. Find a Blender binary of the locked release's minor version, the only one the
   zip supports: --blender, else the first of the BLENDER env var, PATH, and the
   platform's usual install locations that is exactly the locked release, else
   the newest of its minor version.
3. Point BLENDER_USER_RESOURCES at build/blender-user/, which is kept between
   launches (--fresh: empty it first), so Blender reads and writes preferences,
   add-ons, and extensions there, and never the user's own.
4. Install the zip into that dir's user_default repository with Blender's
   extension CLI, enabled, then start Blender with BLENDER_ARGS (e.g. a .blend
   file, or --python SCRIPT).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from blender_paths import blender_candidates, blender_version, pick_release
from blender_release import blender_version as locked_release
from build_extension import ROOT, build

SOURCE_DIR = ROOT / "src" / "proscenium"
USER_DIR = ROOT / "build" / "blender-user"


def find_release_blender(release: str) -> str:
    """An installed Blender binary of `release`'s minor version; exits listing what was found if there is none."""
    major, minor, patch = (int(part) for part in release.split("."))
    wanted = (major, minor, patch)
    installed = [(exe, blender_version(exe)) for exe in blender_candidates()]
    found = pick_release(installed, wanted)
    if found is None:
        listing = "".join(f"\n  {exe}: {'.'.join(map(str, v)) if v else 'unknown version'}" for exe, v in installed)
        raise SystemExit(
            f"no Blender {wanted[0]}.{wanted[1]}.x found; install it or set BLENDER (or pass --blender). "
            f"Found:{listing or ' none'}"
        )
    return found


def isolated_env(user_dir: Path) -> dict[str, str]:
    """This process's environment with every Blender user dir under `user_dir`."""
    # The other BLENDER_USER_* variables override BLENDER_USER_RESOURCES, so drop any the user has set.
    env = {k: v for k, v in os.environ.items() if not k.startswith("BLENDER_USER_")}
    env["BLENDER_USER_RESOURCES"] = str(user_dir)
    return env


def install(blender: str, archive: Path, env: dict[str, str]) -> None:
    """Install and enable `archive` in the user_default repository of `env`'s user dir."""
    cmd = [blender, "--command", "extension", "install-file", "--repo", "user_default", "--enable", str(archive)]
    if subprocess.run(cmd, env=env, check=False).returncode != 0:
        raise SystemExit(f"installing {archive.name} into {blender} failed")
    # Blender keys the wheels it extracts by name and version only, and the workspace's packages keep their version
    # between builds, so install-file leaves an installed build's wheels in place. Removing them and the compatibility
    # cache makes Blender's next startup extract the archive's wheels before it enables the extension. This follows
    # install-file because install-file starts Blender, which enables the extension the preferences name and so needs
    # its wheels.
    extensions = Path(env["BLENDER_USER_RESOURCES"]) / "extensions"
    shutil.rmtree(extensions / ".local", ignore_errors=True)
    (extensions / ".cache" / "compat.dat").unlink(missing_ok=True)


def main() -> int:
    """Build, install, and start Blender; Blender's exit status."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--blender", help="the Blender binary to run, whatever its version")
    parser.add_argument("--fresh", action="store_true", help=f"empty {USER_DIR.relative_to(ROOT)} first")
    parser.add_argument("--no-build", action="store_true", help="install the zip already in dist/")
    parser.add_argument("blender_args", nargs=argparse.REMAINDER, help="arguments for Blender, after --")
    args = parser.parse_args()
    blender_args = args.blender_args[1:] if args.blender_args[:1] == ["--"] else args.blender_args

    if args.no_build:
        manifest = tomllib.loads((SOURCE_DIR / "blender_manifest.toml").read_text(encoding="utf-8"))
        archive = ROOT / "dist" / f"{manifest['id']}-{manifest['version']}.zip"
        if not archive.is_file():
            raise SystemExit(f"{archive} not found; run without --no-build")
    else:
        archive = build(SOURCE_DIR, ROOT / "dist")
    blender = args.blender or find_release_blender(locked_release())
    print(f"using {blender}", flush=True)

    if args.fresh:
        shutil.rmtree(USER_DIR, ignore_errors=True)
    USER_DIR.mkdir(parents=True, exist_ok=True)
    env = isolated_env(USER_DIR)
    install(blender, archive, env)
    return subprocess.run([blender, *blender_args], env=env, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
