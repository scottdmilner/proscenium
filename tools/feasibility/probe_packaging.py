"""Probe 8: build, validate, install, and enable a minimal extension.

First choice is the standalone blender_ext.py CLI shipped inside the bpy wheel,
which needs no Blender binary. run_all.py compares against `blender --command
extension` separately.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from _common import Probe
from _scenes import SCENES
from probe_exchange import EXPECTED, caller_stage

STUBS = Path(__file__).parent / "stubs"
REPO_MODULE = "proscenium_probe_repo"
EXT_ID = "proscenium_probe"


def extension_cli() -> Path:
    import bpy

    scripts = bpy.utils.system_resource("SCRIPTS")  # ty: ignore[unresolved-attribute] - missing from stubs
    return Path(scripts) / "addons_core" / "bl_pkg" / "cli" / "blender_ext.py"


def run() -> dict[str, Any]:
    p = Probe("packaging")
    cli = extension_cli()
    p.fact("extension cli", lambda: str(cli))
    p.check("extension cli exists", cli.exists)
    src = prepare_source(p.tmp / "src")
    dist = p.tmp / "dist"
    dist.mkdir()  # build does not create its output dir

    validate = p.fact("validate", lambda: _run_cli(cli, "validate", str(src)))
    p.check("validate succeeds without a Blender binary", lambda: validate["returncode"], expect=0)
    build = p.fact("build", lambda: _run_cli(cli, "build", "--source-dir", str(src), "--output-dir", str(dist)))
    p.check("build succeeds without a Blender binary", lambda: build["returncode"], expect=0)
    archives = sorted(dist.glob("*.zip"))
    p.check("build produced one archive", lambda: [a.name for a in archives], expect=[f"{EXT_ID}-0.0.1.zip"])
    if archives:
        p.fact("archive contents", lambda: sorted(zipfile.ZipFile(archives[0]).namelist()))
        p.check(
            "validate succeeds on built archive",
            lambda: _run_cli(cli, "validate", str(archives[0]))["returncode"],
            expect=0,
        )
        _install_and_enable(p, archives[0])
    return p.result()


def prepare_source(dest: Path) -> Path:
    """Copy the probe extension and its shared stage inspector into dest."""
    shutil.copytree(STUBS / "probe_extension", dest, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(STUBS / "callee_ext.py", dest / "stage_inspect.py")
    return dest


def _run_cli(cli: Path, *args: str) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, str(cli), *args], capture_output=True, text=True, check=False)
    return {"returncode": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}


def _install_and_enable(p: Probe, archive: Path) -> None:
    """Install into a temporary local repo in-process, enable, exchange a stage, disable."""
    import addon_utils
    import bpy
    from pxr import UsdUtils

    prefs = bpy.context.preferences
    assert prefs is not None
    repos = prefs.extensions.repos
    repo = repos.new(name="Proscenium Probe", module=REPO_MODULE, custom_directory=str(p.tmp / "repo"), source="USER")
    module_name = f"bl_ext.{REPO_MODULE}.{EXT_ID}"
    enabled = False
    try:
        p.fact(
            "install result",
            lambda: sorted(
                bpy.ops.extensions.package_install_files(
                    filepath=str(archive), repo=REPO_MODULE, enable_on_install=True
                )
            ),
        )
        module = sys.modules.get(module_name)
        enabled = module is not None
        p.check(
            "installed extension is enabled and registered",
            lambda: module is not None and module.events,
            expect=["register"],
        )
        if module is not None:
            path = p.tmp / "mesh.usda"
            shutil.copy(SCENES / "exchange" / "mesh.usda", path)
            stage, cache_id = caller_stage(path)
            p.check(
                "installed extension receives caller stage with unsaved and session edits",
                lambda: module.receive_stage(stage, stage.GetRootLayer().identifier, cache_id.ToLongInt()),
                expect=EXPECTED,
            )
            UsdUtils.StageCache.Get().Erase(cache_id)
            p.check(
                "installed extension uses the caller's pxr module",
                lambda: module.stage_inspect.Usd is sys.modules["pxr.Usd"],
            )
            addon_utils.disable(module_name)
            enabled = False
            p.check("disable calls unregister", lambda: module.events, expect=["register", "unregister"])
        p.check("installed files contain no compiled USD", lambda: _bundled_usd(p.tmp / "repo"), expect=[])
    finally:
        if enabled:
            addon_utils.disable(module_name)
        repos.remove(repo)


def _bundled_usd(root: Path) -> list[str]:
    return sorted(str(f.relative_to(root)) for f in root.rglob("*") if "pxr" in f.parts or "usd_ms" in f.name)
