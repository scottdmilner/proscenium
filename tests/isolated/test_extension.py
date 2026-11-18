"""The built extension zip installs, registers on enable, loads its planner, and unregisters on disable.

The zip is conftest.py's extension_zip.
"""

from __future__ import annotations

import io
import tomllib
import zipfile
from pathlib import Path

from blender_deps import current_platform
from blender_release import blender_version
from native_build import wheel_tag

from .harness import Runtime, run_isolated

BODIES = Path(__file__).parent / "bodies"


def test_install_enable_disable(runtime: Runtime, extension_zip: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    result = run_isolated(
        runtime,
        BODIES / "extension.py",
        "install_enable_disable",
        tmp_path,
        archive=str(extension_zip),
        repo_dir=str(repo),
    )
    assert repo in Path(result["module_file"]).parents  # the installed copy, not src/
    for package_file in (result["sync_file"], result["ui_file"]):  # the zip's wheels, not packages/
        assert tmp_path in Path(package_file).parents and "site-packages" in Path(package_file).parts
    assert result["enabled_after_install"]
    registered = result["registered_after_install"]
    assert {"load_post", "undo_post", "redo_post"} <= set(registered["handlers"])
    assert registered["namespaces"] == ["Scene", "Collection", "Text"]
    assert registered["classes"] == ["ProsceniumRecords"]
    assert Path(result["planner_file"]).parent == Path(result["sync_file"]).parent / "planner"
    assert result["planner_usd_version"] == result["host_usd_version"]  # built against this Blender's USD
    assert not result["enabled_after_disable"]
    assert result["registered_after_disable"] == {"handlers": [], "namespaces": [], "classes": []}


def test_zip_names_this_platform_and_release(extension_zip: Path) -> None:
    with zipfile.ZipFile(extension_zip) as archive:
        manifest = tomllib.loads(archive.read("blender_manifest.toml").decode())
        names = archive.namelist()
        (sync_wheel,) = [n for n in names if n.startswith("wheels/proscenium_sync-")]
        with zipfile.ZipFile(io.BytesIO(archive.read(sync_wheel))) as wheel:
            wheel_names = wheel.namelist()
    assert manifest["platforms"] == [str(current_platform())]
    major, minor = blender_version().split(".")[:2]
    assert manifest["blender_version_max"] == f"{major}.{int(minor) + 1}.0"  # the locked minor only
    assert sync_wheel.endswith(f"-{wheel_tag()}.whl")
    assert [n for n in wheel_names if n.startswith("proscenium_sync/planner/_planner.")]  # the compiled module ships
    assert not [n for n in [*names, *wheel_names] if n.endswith((".cpp", ".h", "CMakeLists.txt"))]  # its sources don't
