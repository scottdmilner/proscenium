"""Isolated body: install the built extension zip, enable it, then disable it.

Runs in a fresh Blender process (isolated/harness.py); see tests/isolated/test_extension.py.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import bpy

REPO = "proscenium_test_repo"
PACKAGES = Path(__file__).resolve().parents[3] / "packages"


def install_enable_disable(archive: str, repo_dir: str) -> dict[str, Any]:
    """Install `archive` into a temporary local repo with enable_on_install, load its compiled core, then disable it."""
    import addon_utils  # in the wheel, importable only after bpy

    # Drop the paths to the workspace's packages' sources, so the extension imports them from the zip's wheels.
    sys.path[:] = [p for p in sys.path if not Path(p).is_relative_to(PACKAGES)]

    prefs = bpy.context.preferences
    assert prefs is not None
    prefs.extensions.repos.new(name="Proscenium Test", module=REPO, custom_directory=repo_dir, source="USER")
    bpy.ops.extensions.package_install_files(filepath=archive, repo=REPO, enable_on_install=True)

    name = f"bl_ext.{REPO}.proscenium"
    registration = sys.modules["proscenium_sync.registration"]  # the extension's registration imported it
    result: dict[str, Any] = {
        "module_file": sys.modules[name].__file__,
        "enabled_after_install": name in prefs.addons,
        "registered_after_install": _registrations(registration),
        "sync_file": registration.__file__,
        "ui_file": sys.modules["proscenium_ui"].__file__,
    }
    from pxr import Usd

    core = importlib.import_module("proscenium_sync.core._core")
    result["core_file"] = core.__file__
    result["core_usd_version"] = list(core.usd_version())
    result["host_usd_version"] = list(Usd.GetVersion())
    # default_set=True also removes the preferences entry, as unchecking it in the UI does.
    addon_utils.disable(name, default_set=True)
    result["enabled_after_disable"] = name in prefs.addons
    result["registered_after_disable"] = _registrations(registration)
    return result


def _registrations(registration: Any) -> dict[str, Any]:
    """What the synchronizer's registration has added: its handlers' events, record namespaces, and classes."""
    handlers = bpy.app.handlers
    lists = {name: fns for name in dir(handlers) if isinstance(fns := getattr(handlers, name), list)}
    namespace = registration.id_property_records.NAMESPACE
    return {
        "handlers": sorted(
            event
            for event, fns in lists.items()
            if any(getattr(f, "__module__", None) == registration.__name__ for f in fns)
        ),
        "namespaces": [t.__name__ for t in registration.RECORD_TYPES if hasattr(t, namespace)],
        # Registering gives a class its bl_rna.
        "classes": [c.__name__ for c in registration.CLASSES if "bl_rna" in vars(c)],
    }
