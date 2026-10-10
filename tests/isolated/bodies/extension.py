"""Isolated body: install the built extension zip, enable it, then disable it.

Runs in a fresh Blender process (isolated/harness.py); see tests/isolated/test_extension.py.
"""

from __future__ import annotations

import sys
from typing import Any

import bpy

REPO = "proscenium_test_repo"


def install_enable_disable(archive: str, repo_dir: str) -> dict[str, Any]:
    """Install `archive` into a temporary local repo with enable_on_install, then disable it."""
    import addon_utils  # in the wheel, importable only after bpy

    prefs = bpy.context.preferences
    assert prefs is not None
    prefs.extensions.repos.new(name="Proscenium Test", module=REPO, custom_directory=repo_dir, source="USER")
    bpy.ops.extensions.package_install_files(filepath=archive, repo=REPO, enable_on_install=True)

    name = f"bl_ext.{REPO}.proscenium"
    module = sys.modules[name]
    result: dict[str, Any] = {
        "module_file": module.__file__,
        "enabled_after_install": name in prefs.addons,
        "registered_after_install": module.addon.is_registered(),
    }
    # default_set=True also removes the preferences entry, as unchecking it in the UI does.
    addon_utils.disable(name, default_set=True)
    result["enabled_after_disable"] = name in prefs.addons
    result["registered_after_disable"] = module.addon.is_registered()
    return result
