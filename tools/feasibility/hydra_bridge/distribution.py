"""M1b Phase F: the bridge shipped the way users get it, as a per-platform extension zip.

    uv run python tools/feasibility/hydra_bridge/distribution.py package   # after build.py: the zip
    uv run python tools/feasibility/hydra_bridge/distribution.py install   # installs it into Blender

`package` builds a test zip from a copy of src/proscenium with the bridge module (and its build.json) added to
the core/ package and the manifest's `platforms` set to this platform, using the extension CLI shipped in the
bpy wheel. The bridge stays test code: tools/build_extension.py, the product build, never sees it.

`install` runs three Blender binary sessions over one empty user directory, as a user installing from disk would:
install and enable, then a new session that loads the extension from the saved preferences and runs the loading and
prototype checks against the installed module, then a session that uninstalls it. CI runs `install` on a fresh
runner given only the zip.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPO = "user_default"  # the repository Install from Disk uses
PACKAGE = f"bl_ext.{REPO}.proscenium"
NATIVE = f"{PACKAGE}.core._hydra_bridge"
STAGES = ("install", "session", "uninstall")
# Blender's platform names (blender_ext.py's platform_from_this_system).
SYSTEMS = {"darwin": "macos", "linux": "linux", "windows": "windows"}
MACHINES = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}


# --- Orchestration (uv's Python) ---


def blender_platform() -> str:
    """This machine's platform as a manifest names it, such as macos-arm64."""
    system, machine = platform.system().lower(), platform.machine().lower()
    return f"{SYSTEMS.get(system, system)}-{MACHINES.get(machine, machine)}"


def package(module_dir: Path, out: Path) -> Path:
    from blender_paths import wheel_extension_cli

    cli = wheel_extension_cli()
    if cli is None:
        raise SystemExit("bpy wheel not found: run from the uv environment (uv sync)")
    modules = sorted(module_dir.glob("_hydra_bridge.*"))
    if len(modules) != 1:
        raise SystemExit(f"expected one built module in {module_dir}, found {modules}; run build.py")
    out.mkdir(parents=True, exist_ok=True)  # the CLI does not create it
    with tempfile.TemporaryDirectory(prefix="proscenium-dist-") as tmp:
        staged = Path(tmp) / "proscenium"
        shutil.copytree(ROOT / "src" / "proscenium", staged, ignore=shutil.ignore_patterns("__pycache__", "wheels"))
        for path in (modules[0], module_dir / "build.json"):
            shutil.copy2(path, staged / "core" / path.name)
        manifest = staged / "blender_manifest.toml"
        text = manifest.read_text(encoding="utf-8")
        # The generated block holds the top-level keys; Proscenium has no runtime wheels, so it is empty.
        text, count = re.subn(
            r"^# --- end generated ---$", f'platforms = ["{blender_platform()}"]\n\\g<0>', text, flags=re.M
        )
        if count != 1:
            raise SystemExit(f"{manifest}: no generated-block end marker")
        manifest.write_text(text, encoding="utf-8")
        for args in (
            ["validate", str(staged)],
            ["build", "--split-platforms", "--source-dir", str(staged), "--output-dir", str(out)],
        ):
            subprocess.run([sys.executable, str(cli), *args], check=True)
    archives = sorted(out.glob(f"proscenium-*-{blender_platform().replace('-', '_')}.zip"))
    if len(archives) != 1:
        raise SystemExit(f"expected one zip in {out}, found {archives}")
    subprocess.run([sys.executable, str(cli), "validate", str(archives[0])], check=True)
    return archives[0]


def install(archive: Path, blender: str, out: Path) -> bool:
    passed = True
    with tempfile.TemporaryDirectory(prefix="proscenium-user-") as user_dir:
        env = {**os.environ, "BLENDER_USER_RESOURCES": user_dir}
        for stage in STAGES:
            result_path = out / f"distribution-{stage}.json"
            result_path.unlink(missing_ok=True)
            # No --factory-startup: the later sessions must load the preferences the first one saved.
            command = [blender, "--background", "--python-exit-code", "1", "--python", __file__, "--"]
            command += [stage, str(archive.resolve()), str(result_path)]
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=300, check=False)
            (out / f"distribution-{stage}.log").write_text(result.stdout + result.stderr)
            print(f"distribution-{stage}: exit {result.returncode}")
            print((result.stdout + result.stderr)[-5000:])
            passed = passed and result.returncode == 0 and result_path.exists()
            if not passed:
                break
    return passed


def main() -> int:
    sys.path.insert(0, str(HERE.parents[1]))
    from blender_paths import find_blender

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["package", "install"])
    parser.add_argument("--out", type=Path, default=ROOT / "build/hydra-bridge")
    parser.add_argument("--archive", type=Path, help="install: the zip (default: the one package wrote)")
    parser.add_argument("--blender", default=find_blender(), help="Blender binary (default: BLENDER or the default)")
    args = parser.parse_args()
    out = args.out.resolve()
    dist = out / "dist"
    if args.command == "package":
        print(f"built {package(out, dist)}")
        return 0
    if not args.blender:
        parser.error("no Blender binary found: set BLENDER or pass --blender")
    archives = [args.archive] if args.archive else sorted(dist.glob("proscenium-*.zip"))
    if len(archives) != 1:
        parser.error(f"expected one zip in {dist}, found {archives}; pass --archive")
    out.mkdir(parents=True, exist_ok=True)
    return 0 if install(archives[0], args.blender, out) else 1


# --- Stages (inside the Blender binary) ---


class Checks:
    def __init__(self) -> None:
        self.checks: list[str] = []
        self.facts: dict[str, Any] = {}

    def __call__(self, name: str, condition: bool, detail: object = None) -> None:
        if not condition:
            raise AssertionError(name if detail is None else f"{name}: {detail}")
        self.checks.append(name)


def run_stage(stage: str, archive: Path) -> dict[str, Any]:
    import bpy

    check = Checks()
    prefs = bpy.context.preferences
    assert prefs is not None
    user = Path(os.environ["BLENDER_USER_RESOURCES"]).resolve()
    repo_index = next(i for i, repo in enumerate(prefs.extensions.repos) if repo.module == REPO)
    repo_dir = Path(prefs.extensions.repos[repo_index].directory).resolve()
    check("the user repository is in this run's user directory", user in repo_dir.parents, repo_dir)
    installed = repo_dir / "proscenium"
    if stage == "install":
        _install(check, archive, installed)
    elif stage == "session":
        _session(check, installed)
    else:
        _uninstall(check, repo_index, installed)
    return {"stage": stage, "checks": check.checks, "facts": check.facts, "blender": bpy.app.version_string}


def _install(check: Checks, archive: Path, installed: Path) -> None:
    import bpy

    check.facts["archive"] = archive.name
    other = _for_other_platform(archive, Path(tempfile.mkdtemp(prefix="proscenium-other-")) / archive.name)
    try:
        refused = bpy.ops.extensions.package_install_files(filepath=str(other), repo=REPO, enable_on_install=True)
    except RuntimeError as error:  # an operator's error report, in background mode
        refused = str(error)
    check.facts["another platform's zip"] = str(refused)
    check("another platform's zip is refused", not installed.exists(), refused)
    result = bpy.ops.extensions.package_install_files(filepath=str(archive), repo=REPO, enable_on_install=True)
    check("install from disk finishes", result == {"FINISHED"}, result)
    prefs = bpy.context.preferences
    assert prefs is not None
    check("installed extension is enabled", PACKAGE in prefs.addons and PACKAGE in sys.modules)
    files = sorted(str(f.relative_to(installed)) for f in installed.rglob("*") if f.is_file())
    check.facts["installed files"] = [f for f in files if "__pycache__" not in f]
    check("installed package holds the bridge module", any(Path(f).name.startswith("_hydra_bridge.") for f in files))
    check("installed package bundles no USD", not [f for f in files if "pxr" in Path(f).parts or "usd_ms" in f])
    check("enabling doesn't load the compiled module", NATIVE not in sys.modules)
    bpy.ops.wm.save_userpref()


def _for_other_platform(archive: Path, dest: Path) -> Path:
    """A copy of the zip whose manifest names another platform."""
    import re
    import zipfile

    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as copy:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == "blender_manifest.toml":
                ours = "windows-x64" if sys.platform == "darwin" else "macos-arm64"
                data = re.sub(rb"^platforms = .*$", f'platforms = ["{ours}"]'.encode(), data, flags=re.M)
            copy.writestr(item, data)
    return dest


def _session(check: Checks, installed: Path) -> None:
    import addon_utils
    import bpy
    from pxr import Usd

    sys.path.insert(0, str(HERE))
    import probe
    import prototype_probe

    prefs = bpy.context.preferences
    assert prefs is not None
    check("a new session enables the extension from saved preferences", PACKAGE in prefs.addons)
    check("and loads it at startup", PACKAGE in sys.modules)
    native = importlib.import_module(NATIVE)
    module = Path(str(native.__file__)).resolve()
    check("the compiled module loads from the installed package", module.parent == installed / "core", module)
    loading = probe.run(module.parent, native)
    check.facts["loading checks"] = len(loading["checks"])
    check.facts["loaded usd libraries"] = loading["loaded_usd_libraries"]
    prototype = prototype_probe.run(module.parent, native)
    check.facts["prototype checks"] = len(prototype["checks"])
    check("loading and prototype checks pass from the installed module", True)

    addon_utils.disable(PACKAGE, default_set=True)
    check("disable turns the extension off", PACKAGE not in prefs.addons)
    # Python never unloads a compiled module; record what disabling leaves.
    check.facts["compiled module still imported after disable"] = NATIVE in sys.modules
    addon_utils.enable(PACKAGE, default_set=True)
    check("enable turns it back on", PACKAGE in prefs.addons)
    again = importlib.import_module(NATIVE)
    check.facts["re-enabled extension imports the same module object"] = again is native
    stage = Usd.Stage.CreateInMemory()
    stage.DefinePrim("/Cube", "Cube")
    bridge = again.Bridge(stage)
    check("the re-enabled extension's module still captures", "/Cube" in bridge.capture(0.0).paths())
    bridge.release()


def _uninstall(check: Checks, repo_index: int, installed: Path) -> None:
    import bpy

    prefs = bpy.context.preferences
    assert prefs is not None
    check("the extension is enabled at startup", PACKAGE in prefs.addons)
    check("without its compiled module loaded", NATIVE not in sys.modules)
    result = bpy.ops.extensions.package_uninstall(repo_index=repo_index, pkg_id="proscenium")
    check("uninstall finishes", result == {"FINISHED"}, result)
    check("uninstall removes the installed files", not installed.exists())
    check("and disables the extension", PACKAGE not in prefs.addons)


if __name__ == "__main__":
    if "--" in sys.argv:  # a stage inside Blender
        stage, archive, result_path = sys.argv[sys.argv.index("--") + 1 :]
        result = run_stage(stage, Path(archive))
        Path(result_path).write_text(json.dumps(result, indent=2) + "\n")
        print(f"distribution {stage}: {len(result['checks'])} checks passed")
    else:
        sys.exit(main())
