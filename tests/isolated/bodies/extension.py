"""Isolated body: install the built extension zip, enable it, then disable it.

Runs in a fresh Blender process (isolated/harness.py); see tests/isolated/test_extension.py.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

import bpy

REPO = "proscenium_test_repo"


def install_enable_disable(archive: str, repo_dir: str) -> dict[str, Any]:
    """Install `archive` into a temporary local repo with enable_on_install, load its compiled core, then disable it."""
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
        "registered_after_install": _registrations(module.addon),
    }
    from pxr import Usd

    core = importlib.import_module(f"{name}.core._core")
    result["core_file"] = core.__file__
    result["core_usd_version"] = list(core.usd_version())
    result["host_usd_version"] = list(Usd.GetVersion())
    # default_set=True also removes the preferences entry, as unchecking it in the UI does.
    addon_utils.disable(name, default_set=True)
    result["enabled_after_disable"] = name in prefs.addons
    result["registered_after_disable"] = _registrations(module.addon)
    return result


def _registrations(addon: Any) -> dict[str, Any]:
    """What the installed extension has added to Blender: its handlers' events, record namespaces, and classes."""
    handlers = bpy.app.handlers
    lists = {name: fns for name in dir(handlers) if isinstance(fns := getattr(handlers, name), list)}
    return {
        "handlers": sorted(
            event for event, fns in lists.items() if any(getattr(f, "__module__", None) == addon.__name__ for f in fns)
        ),
        "namespaces": [t.__name__ for t in addon.RECORD_TYPES if hasattr(t, addon.records.NAMESPACE)],
        "classes": [c.__name__ for c in addon.CLASSES if "bl_rna" in vars(c)],  # registering gives a class its bl_rna
    }
