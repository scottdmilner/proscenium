"""Phase B smoke checks: capture -> C++ plan -> Blender on prototype.usda, in a fresh wheel or Blender process.

Expected values come from USD (UsdGeom, UsdShade) or from how the scene is built, never from Hydra.
Phase C's per-case scenes check correctness in depth; these check that each path of the slice works.
"""

from __future__ import annotations

import importlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TIME = 1.0


def run(module_dir: Path) -> dict[str, Any]:
    import bpy
    from pxr import Usd, UsdGeom, UsdShade

    sys.path.insert(0, str(HERE))
    import apply

    checks: list[str] = []

    def check(name: str, condition: bool, detail: object = None) -> None:
        if not condition:
            raise AssertionError(name if detail is None else f"{name}: {detail}")
        checks.append(name)

    sys.path.insert(0, str(module_dir))
    native = importlib.import_module("_hydra_bridge")

    with tempfile.TemporaryDirectory(prefix="hydra-prototype-scene-") as tmp:
        scene = Path(tmp) / "prototype.usda"
        shutil.copy(HERE / "prototype.usda", scene)
        stage = Usd.Stage.Open(str(scene))
        bridge = native.Bridge(stage)
        snapshot = bridge.capture(TIME)
        plan = native.build_plan(snapshot)
        diagnostics = plan.diagnostics
        errors = [d for d in diagnostics if d["severity"] == "error"]
        check("plan has no error diagnostics", not errors, errors)
        # The snapshot holds Hydra's static copies of the schemas planning reads, whole, and nothing else:
        # the root's system container (asset resolution) is not copied.
        grid_dump, root_dump = snapshot.dump("/World/Grid"), snapshot.dump("/")
        check(
            "snapshot copies the planned schemas whole, and no others",
            "subdivisionTags" in grid_dump and "__usdPrimInfo" in grid_dump and "system" not in root_dump,
            root_dump,
        )

        objects = plan.objects
        by_source = {o["source"]: o for o in objects}
        expected = _drawn_gprims(stage)
        check("one object per source", len(by_source) == len(objects), [o["source"] for o in objects])
        check(
            "one object per drawn gprim, with its native-instance context",
            {source: o["instance_context"] for source, o in by_source.items()} == expected,
            (sorted(by_source), sorted(expected)),
        )
        cache = UsdGeom.XformCache(TIME)
        wrong = [s for s, o in by_source.items() if not _close(o["matrix"], _world(cache, stage, s))]
        check("world transforms match UsdGeom", not wrong, wrong)
        wrong = [s for s, o in by_source.items() if o["primvars"].get("displayColor") != _display_color(stage, s)]
        check("displayColor matches USD primvar inheritance through instances", not wrong, wrong)

        def codes(source: str) -> set[str]:
            return {d["code"] for d in diagnostics if d["source"] == source}

        check("approximated sphere is diagnosed", "approximated-surface" in codes("/World/Ball"))
        check("exact cube is not diagnosed", "approximated-surface" not in codes("/World/Box"))
        hair = by_source["/World/Hair"]
        check(
            "basis curves become a placeholder with a diagnostic",
            hair["mesh"] is None
            and hair["placeholder_type"] == "basisCurves"
            and "untranslated-type" in codes("/World/Hair"),
        )

        formats = {
            "positions": ("f", 2),
            "corner_verts": ("i", 1),
            "face_offsets": ("i", 1),
            "material_indices": ("i", 1),
        }
        views = [memoryview(mesh[key]) for mesh in plan.meshes for key in formats]
        check(
            "plan arrays are read-only contiguous buffers in Blender's element types",
            all(v.readonly and v.c_contiguous for v in views)
            and all(
                (memoryview(mesh[key]).format, memoryview(mesh[key]).ndim) == fmt
                for mesh in plan.meshes
                for key, fmt in formats.items()
            ),
        )
        red = UsdShade.Shader(stage.GetPrimAtPath("/World/Looks/Red/Surface")).GetInput("diffuseColor").Get()
        (red_material,) = [m for m in plan.materials if "/World/Looks/Red" in m["sources"]]
        check(
            "material surface parameters match the shader",
            red_material["surface_identifier"] == "UsdPreviewSurface"
            and red_material["parameters"]["diffuseColor"] == red,
        )

        collection = bpy.data.collections.new("HydraPrototype")
        blender_scene: Any = bpy.context.scene  # never None in a running Blender
        blender_scene.collection.children.link(collection)
        created: dict[str, Any] = dict(zip((o["source"] for o in objects), apply.apply(plan, collection), strict=True))
        check("every planned object reaches Blender", all(o.name in collection.objects for o in created.values()))
        check("placeholder is an empty", created["/World/Hair"].type == "EMPTY")

        grid = created["/World/Grid"].data
        usd_grid: Any = UsdGeom.Mesh(stage.GetPrimAtPath("/World/Grid"))  # stubs: Gf values are not iterable
        check("Blender accepts the mesh unchanged", not grid.validate())
        check(
            "positions reach Blender",
            [tuple(v.co) for v in grid.vertices] == [tuple(p) for p in usd_grid.GetPointsAttr().Get(TIME)],
        )
        check(
            "topology reaches Blender",
            [loop.vertex_index for loop in grid.loops] == list(usd_grid.GetFaceVertexIndicesAttr().Get(TIME))
            and [p.loop_total for p in grid.polygons] == list(usd_grid.GetFaceVertexCountsAttr().Get(TIME)),
        )
        st: Any = UsdGeom.PrimvarsAPI(usd_grid).GetPrimvar("st").ComputeFlattened(TIME)
        check(
            "indexed face-varying UVs reach a UV map",
            "st" in grid.uv_layers and [tuple(d.uv) for d in grid.uv_layers["st"].data] == [tuple(v) for v in st],
        )
        face_materials = [grid.materials[p.material_index]["proscenium_sources"] for p in grid.polygons]
        expected_materials = _face_materials(stage, usd_grid)
        check(
            "GeomSubset faces get the subset's material slot",
            all(path in sources for path, sources in zip(expected_materials, face_materials, strict=True)),
            (expected_materials, face_materials),
        )
        shared: dict[int, set[str]] = {}
        for o in objects:
            if o["mesh"] is not None:
                shared.setdefault(o["mesh"], set()).add(created[o["source"]].data.name)
        check("objects sharing a plan mesh share Blender mesh data", all(len(names) == 1 for names in shared.values()))

        # The snapshot and plan are immutable: a later edit reaches only the next capture.
        before = list(snapshot.prim("/World/Grid")["points"])
        grid_mesh = by_source["/World/Grid"]["mesh"]
        usd_grid.GetPointsAttr().Set([(x, y, 5.0) for x, y, _ in before], TIME)
        after = bridge.capture(TIME)
        check(
            "snapshot and plan are unchanged by later edits",
            list(snapshot.prim("/World/Grid")["points"]) == before
            and list(plan.meshes[grid_mesh]["positions"]) == before
            and after.prim("/World/Grid")["points"][0][2] == 5.0,
        )
        bridge.release()
        return {
            "checks": checks,
            "blender": bpy.app.version_string,
            "objects": len(objects),
            "meshes": len(plan.meshes),
            "materials": len(plan.materials),
            "diagnostics": diagnostics,
        }


def _drawn_gprims(stage: Any) -> dict[str, tuple[str, ...]]:
    """Every gprim USD draws, through instance proxies, with its native instance roots, outermost first."""
    from pxr import Usd, UsdGeom

    result = {}
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies(Usd.PrimDefaultPredicate)):
        if prim.IsA(UsdGeom.Gprim):  # ty: ignore[no-matching-overload] - IsA also takes a schema class
            roots = []
            ancestor = prim.GetParent()
            while ancestor and not ancestor.IsPseudoRoot():
                if ancestor.IsInstance():
                    roots.append(str(ancestor.GetPath()))
                ancestor = ancestor.GetParent()
            result[str(prim.GetPath())] = tuple(reversed(roots))
    return result


def _world(cache: Any, stage: Any, source: str) -> Any:
    return cache.GetLocalToWorldTransform(stage.GetPrimAtPath(source))


def _close(a: Any, b: Any) -> bool:
    return all(abs(a[row][col] - b[row][col]) < 1e-5 for row in range(4) for col in range(4))


def _display_color(stage: Any, source: str) -> Any:
    from pxr import UsdGeom

    primvar = UsdGeom.PrimvarsAPI(stage.GetPrimAtPath(source)).FindPrimvarWithInheritance("displayColor")
    return primvar.Get(TIME) if primvar and primvar.HasAuthoredValue() else None


def _face_materials(stage: Any, mesh: Any) -> list[str]:
    """Each face's bound material: its materialBind subset's, else the mesh's."""
    from pxr import UsdGeom, UsdShade

    def bound(prim: Any) -> str:
        return str(UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0].GetPath())

    faces = [bound(mesh.GetPrim())] * len(mesh.GetFaceVertexCountsAttr().Get(TIME))
    for subset in UsdGeom.Subset.GetGeomSubsets(mesh, "face", "materialBind"):
        for face in subset.GetIndicesAttr().Get(TIME):
            faces[face] = bound(subset.GetPrim())
    return faces


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    result = run(Path(args[0]))
    Path(args[1]).write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(f"Hydra prototype: {len(result['checks'])} checks passed")
