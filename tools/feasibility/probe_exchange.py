"""Probe 2: can caller code hand a Usd.Stage to extension code in-process?

The installed-extension variant of this check runs in probe_packaging.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any

from _common import Probe
from _scenes import SCENES

STUBS = Path(__file__).parent / "stubs"


def run() -> dict[str, Any]:
    import bpy
    from pxr import Usd, UsdUtils

    p = Probe("exchange")
    path = p.tmp / "mesh.usda"
    shutil.copy(SCENES / "exchange" / "mesh.usda", path)
    original = path.read_bytes()
    callee = load_module(STUBS / "callee_ext.py", "proscenium_probe_callee")

    stage, cache_id = caller_stage(path)
    p.check(
        "callee receives caller stage with unsaved and session edits",
        lambda: callee.inspect(stage, stage.GetRootLayer().identifier, cache_id.ToLongInt()),
        expect=EXPECTED,
    )
    anon = Usd.Stage.CreateInMemory()
    anon.DefinePrim("/Extra")
    p.check(
        "callee receives anonymous in-memory stage",
        lambda: callee.inspect(anon, anon.GetRootLayer().identifier, 0)["sees_unsaved_prim"],
    )
    p.fact("pxr_module_shared", lambda: sys.modules["pxr.Usd"] is callee.Usd)

    # Does Blender's C++ USD importer share the Python layer registry?
    bpy.ops.wm.read_factory_settings(use_empty=True)
    p.fact("blender_importer_result", lambda: sorted(bpy.ops.wm.usd_import(filepath=str(path))))
    names = sorted(o.name for o in bpy.data.objects)
    p.fact("blender_importer_objects", lambda: names)
    p.fact(
        "blender_importer_sees_unsaved_python_edits",
        lambda: any(n.startswith("Extra") for n in names),
    )
    p.check("source file unchanged by import", lambda: path.read_bytes() == original)
    UsdUtils.StageCache.Get().Erase(cache_id)
    return p.result()


EXPECTED = {
    "is_stage": True,
    "sees_unsaved_prim": True,
    "sees_session_prim": True,
    "same_root_layer": True,
    "cache_lookup_is_same_stage": True,
}


def caller_stage(path: Path) -> tuple[Any, Any]:
    """Caller stage with an unsaved root-layer edit and a session-layer opinion,
    registered in the global UsdUtils.StageCache. Returns (stage, cache id);
    the caller erases the cache entry."""
    from pxr import Sdf, Usd, UsdUtils

    stage = Usd.Stage.Open(str(path))
    Sdf.CopySpec(stage.GetRootLayer(), "/Tri", stage.GetRootLayer(), "/Extra")
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        stage.DefinePrim("/SessionOnly")
    return stage, UsdUtils.StageCache.Get().Insert(stage)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
