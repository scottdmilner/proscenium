"""Run assertions inside a fresh wheel or Blender process; write JSON evidence."""

from __future__ import annotations

import gc
import importlib
import importlib.metadata
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


def run(module_dir: Path) -> dict[str, Any]:
    import bpy
    from pxr import Gf, Sdf, Usd, UsdGeom, Vt

    checks: list[str] = []

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    # Windows resolves usd_ms.dll through the loaded-module list; fail clearly if the host hasn't loaded it.
    if sys.platform == "win32":
        import ctypes

        check(
            "host loaded usd_ms.dll before the bridge", bool(ctypes.WinDLL("kernel32").GetModuleHandleW("usd_ms.dll"))
        )
    sys.path.insert(0, str(module_dir))
    native = importlib.import_module("_hydra_bridge")

    with tempfile.TemporaryDirectory(prefix="hydra-bridge-scene-") as tmp:
        scene = Path(tmp) / "scene.usda"
        shutil.copy(Path(__file__).with_name("scene.usda"), scene)
        original_file = scene.read_bytes()
        stage = Usd.Stage.Open(str(scene))
        stage.DefinePrim("/Unsaved", "Xform")
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            stage.DefinePrim("/SessionOnly", "Xform")
        layers_before = [layer.ExportToString() for layer in (stage.GetRootLayer(), stage.GetSessionLayer())]
        bridge = native.Bridge(stage)
        check("native stage round-trip preserves identity", bridge.stage() == stage)
        check("native root layer is caller's layer", bridge.stage().GetRootLayer() == stage.GetRootLayer())
        # Captures are at explicit numeric time codes; time 1 is the fixture's first points sample.
        initial = bridge.capture(1.0)
        paths = initial.paths()
        check("unsaved root and session opinions visible", "/Unsaved" in paths and "/SessionOnly" in paths)
        tri = initial.prim("/World/Tri")
        check("mesh topology extracted", list(tri["counts"]) == [3] and list(tri["indices"]) == [0, 1, 2])
        check("existing Vt converter used", isinstance(tri["points"], Vt.Vec3fArray))
        check(
            "time-sampled points extracted",
            list(tri["points"]) == [Gf.Vec3f(0, 0, 0), Gf.Vec3f(1, 0, 0), Gf.Vec3f(0, 1, 0)],
        )
        check("inherited world transform flattened", tri["matrix"].ExtractTranslation() == Gf.Vec3d(10, 0, 0))
        cube = initial.prim("/World/Cube")
        check(
            "cube converted to mesh",
            cube["type"] == "mesh" and len(cube["points"]) == 8 and list(cube["counts"]) == [4] * 6,
        )
        check("cube dimensions preserved", all(abs(component) == 1 for point in cube["points"] for component in point))
        types = {initial.prim(path)["type"] for path in paths}
        check("native instancing produces instancer data", "instancer" in types)
        check(
            "capture leaves source layers unchanged",
            layers_before == [layer.ExportToString() for layer in (stage.GetRootLayer(), stage.GetSessionLayer())],
        )

        middle = bridge.capture(2.0)
        check("interpolated explicit time", middle.prim("/World/Tri")["points"][1] == Gf.Vec3f(2, 0, 0))
        check("time change produces dirty notice", ("dirtied", "/World/Tri") in middle.events)
        check("unchanged capture produces no notices", bridge.capture(2.0).events == [])
        check("return to an earlier time", bridge.capture(1.0).prim("/World/Tri")["points"][1] == Gf.Vec3f(1, 0, 0))

        attr = UsdGeom.Mesh(stage.GetPrimAtPath("/World/Tri")).GetPointsAttr()
        attr.Set([(0, 0, 0), (7, 0, 0), (0, 7, 0)], 1.0)
        edited = bridge.capture(1.0)
        check(
            "live Python edit reaches retained Hydra chain", edited.prim("/World/Tri")["points"][1] == Gf.Vec3f(7, 0, 0)
        )
        check("live edit produces dirty notice", ("dirtied", "/World/Tri") in edited.events)
        # The fixture's default points equal the time-1 sample; that sample is now edited, so default time
        # must read the authored default value, not a sample.
        default = bridge.capture()
        check("default time reads default values", default.prim("/World/Tri")["points"][1] == Gf.Vec3f(1, 0, 0))
        check("default time reports no numeric time", default.time is None and edited.time == 1.0)
        check(
            "None and Usd.TimeCode select times",
            bridge.capture(None).prim("/World/Tri")["points"][1] == Gf.Vec3f(1, 0, 0)
            and bridge.capture(Usd.TimeCode(1.0)).prim("/World/Tri")["points"][1] == Gf.Vec3f(7, 0, 0),
        )
        check("non-time argument raises", _raises(lambda b=bridge: b.capture("now"), TypeError))
        UsdGeom.Imageable(stage.GetPrimAtPath("/World")).GetVisibilityAttr().Set("invisible")
        check("inherited visibility updates", bridge.capture(1.0).prim("/World/Tri")["visible"] is False)
        stage.DefinePrim("/Added", "Xform")
        added = bridge.capture(1.0)
        check("added prim propagates", "/Added" in added.paths() and ("added", "/Added") in added.events)
        stage.RemovePrim("/Added")
        removed = bridge.capture(1.0)
        check("removed prim propagates", "/Added" not in removed.paths() and ("removed", "/Added") in removed.events)
        check("source file never saved", scene.read_bytes() == original_file)

        del bridge, stage, attr
        gc.collect()
        check("captured array survives edits and bridge disposal", tri["points"][1] == Gf.Vec3f(1, 0, 0))
        check("snapshot outlives its bridge", initial.prim("/World/Tri")["points"][1] == Gf.Vec3f(1, 0, 0))
        anonymous = Usd.Stage.CreateInMemory()
        anonymous.DefinePrim("/Anonymous", "Xform")
        layer_id = anonymous.GetRootLayer().identifier
        anon_bridge = native.Bridge(anonymous)
        check(
            "anonymous stage round-trip",
            anon_bridge.stage() == anonymous and "/Anonymous" in anon_bridge.capture(0.0).paths(),
        )
        del anonymous
        gc.collect()
        # The stage scene index holds a strong reference until the bridge releases its chain.
        check("unreleased chain keeps a caller-released stage alive", Sdf.Layer.Find(layer_id) is not None)
        anon_bridge.release()
        gc.collect()
        check("released bridge lets a caller-released stage expire", Sdf.Layer.Find(layer_id) is None)
        check("released bridge reports no stage", anon_bridge.stage() is None)
        check("capture after release raises", _raises(lambda b=anon_bridge: b.capture(0.0), RuntimeError))
        del anon_bridge
        for _ in range(20):
            transient = Usd.Stage.CreateInMemory()
            transient.DefinePrim("/Repeated", "Xform")
            instance = native.Bridge(transient)
            assert "/Repeated" in instance.capture(0.0).paths()
            del instance, transient
        check("repeated construction and disposal", True)
        check("invalid stage raises", _raises(lambda: native.Bridge(None), Exception))

        libraries = list(native.loaded_usd_libraries())
        check("exactly one loaded USD library", len(libraries) == 1)
        root = _host_root(Usd.__file__, bpy.app.version)
        check("loaded USD belongs to host Blender", _same(libraries[0], _host_usd(root)))
        check("bridge binds USD to the loaded library", _same(native.usd_providing_library(), libraries[0]))
        check("Python pxr is the host's", Path(Usd.__file__).resolve().is_relative_to(root.resolve()))
        check("no pip usd-core installed", _missing_distribution("usd-core"))
        check("bridge built for the host's USD", native.usd_version == tuple(Usd.GetVersion()))
        # build.py records the Blender release whose headers built the module, beside the module.
        built = json.loads((module_dir / "build.json").read_text(encoding="utf-8"))
        check(
            "host Blender is the release the bridge was built against",
            built["blender_commit"].startswith(bpy.app.build_hash.decode()),
        )
        return {
            "checks": checks,
            "blender": bpy.app.version_string,
            "usd": Usd.GetVersion(),
            "usd_namespace": native.usd_namespace,
            "loaded_usd_libraries": libraries,
            "module": native.__file__,
            "prim_types": sorted(types),
        }


def _raises(fn: Any, kind: type[BaseException]) -> bool:
    try:
        fn()
    except kind:
        return True
    return False


def _host_root(usd_file: str, version: tuple[int, ...]) -> Path:
    """The directory holding Blender's '<major>.<minor>' resources: bpy/ in the wheel, the install root otherwise."""
    series = f"{version[0]}.{version[1]}"
    return next(parent.parent for parent in Path(usd_file).resolve().parents if parent.name == series)


def _host_usd(root: Path) -> Path:
    # Wheel: bpy/lib/ (macOS, Linux) or beside bpy/__init__.pyd (Windows).
    # Binary: lib/ (Linux), Contents/Resources/lib/ (macOS root is Resources), blender.shared/ (Windows).
    candidates = [root / "lib/libusd_ms.dylib", root / "lib/libusd_ms.so", root / "usd_ms.dll"]
    candidates.append(root / "blender.shared/usd_ms.dll")
    found = [path for path in candidates if path.exists()]
    if len(found) != 1:
        raise AssertionError(f"expected one host USD library under {root}, found {found}")
    return found[0]


def _same(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(Path(a).resolve()) == os.path.normcase(Path(b).resolve())


def _missing_distribution(name: str) -> bool:
    try:
        importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return True
    return False


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    result = run(Path(args[0]))
    Path(args[1]).write_text(json.dumps(result, indent=2) + "\n")
    print(f"Hydra bridge: {len(result['checks'])} checks passed")
