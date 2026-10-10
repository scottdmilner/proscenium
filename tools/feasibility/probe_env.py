"""Probe 1: Blender build, Python, USD version, modules, and plugins."""

from __future__ import annotations

import importlib
import os
import pkgutil
import platform
import sys
from pathlib import Path
from typing import Any

from _common import Probe

# Modules later milestones are expected to need.
REQUIRED_PXR = ["Usd", "UsdGeom", "UsdShade", "UsdLux", "UsdSkel", "Sdf", "Ar", "Tf", "Vt", "Gf", "Plug", "UsdUtils"]


def run() -> dict[str, Any]:
    import bpy

    p = Probe("env")
    p.fact(
        "platform", lambda: {"system": platform.system(), "machine": platform.machine(), "release": platform.release()}
    )
    p.fact(
        "blender",
        lambda: {
            "version": bpy.app.version_string,
            "build_hash": bpy.app.build_hash,
            "build_date": bpy.app.build_date,
            "build_platform": bpy.app.build_platform,
            "binary_path": bpy.app.binary_path,
            "background": bpy.app.background,
            "bpy_file": bpy.__file__,
        },
    )
    p.fact("python", lambda: {"version": sys.version, "executable": sys.executable})

    import pxr
    from pxr import Ar, Plug, Usd

    p.fact("usd_version", lambda: ".".join(map(str, Usd.GetVersion())))
    p.fact("pxr_path", lambda: list(pxr.__path__))
    p.check("exactly one pxr package on sys.path", lambda: len(_pxr_copies()), expect=1)
    p.fact("pxr copies on sys.path", _pxr_copies)
    p.check("no installed distribution ships its own pxr package", _usd_distributions, expect=[])
    available = sorted(m.name for m in pkgutil.iter_modules(pxr.__path__))
    p.fact("pxr_modules", lambda: available)
    p.check("required pxr modules import", lambda: [m for m in REQUIRED_PXR if not _imports(f"pxr.{m}")], expect=[])
    p.fact("unimportable_pxr_modules", lambda: [m for m in available if not _imports(f"pxr.{m}")])
    p.fact(
        "plugins",
        lambda: sorted((pl.name, pl.path) for pl in Plug.Registry().GetAllPlugins()),
    )
    p.fact("plugin_env", lambda: {k: v for k, v in os.environ.items() if k.startswith(("PXR_", "BLENDER_"))})
    p.fact("resolver", lambda: type(Ar.GetResolver()).__name__)
    p.fact("materialx", lambda: _version("MaterialX", "getVersionString"))
    p.check("blender has usd importer", lambda: hasattr(bpy.ops.wm, "usd_import"))
    return p.result()


def _pxr_copies() -> list[str]:
    return sorted({str(Path(e, "pxr").resolve()) for e in sys.path if e and Path(e, "pxr", "__init__.py").is_file()})


def _usd_distributions() -> list[str]:
    from importlib import metadata

    # A top-level pxr/ (e.g. usd-core). bpy's pxr is nested under bpy/ and
    # stub packages install pxr-stubs/, so neither counts.
    return sorted(
        d.metadata["Name"] or "?" for d in metadata.distributions() if any(f.parts[0] == "pxr" for f in d.files or [])
    )


def _imports(name: str) -> bool:
    try:
        importlib.import_module(name)
    except Exception:  # noqa: BLE001
        return False
    return True


def _version(module: str, getter: str) -> str:
    return getattr(importlib.import_module(module), getter)()
