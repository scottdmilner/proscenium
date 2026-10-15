"""One measured synchronization in the Blender binary: Blender's USD importer, or the Hydra prototype.

    blender --background --factory-startup --python child.py -- <config.json>

The config names the mode, scene, time code, module directory, and output paths. The child writes a marker
(JSON line) at every stage boundary with its CPU time and lifetime memory peaks; the parent samples the
process from outside and aligns its samples to these markers. Settle windows hold still for a while so the
parent can read memory at rest.
"""

from __future__ import annotations

import gc
import json
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import bpy  # noqa: E402
import memory  # noqa: E402

# The importer's options closest to what the prototype builds: every purpose, invisible prims too, no
# Principled networks, and none of the types the prototype only marks with placeholders. Shapes stay on,
# since the prototype turns implicit surfaces into meshes; instancing stays on, as the prototype shares
# meshes between instances. Unit scaling is off: the prototype doesn't apply metersPerUnit. "Expanded" also
# turns scene instancing off: with it on, the importer drops materials bound at or above an instance root
# (measured on the instancing stress scene), which the prototype honors; with it off, every instance gets
# its own object and mesh.
MATCHED = {
    "import_cameras": False,
    "import_curves": False,
    "import_lights": False,
    "import_volumes": False,
    "import_points": False,
    "import_skeletons": False,
    "import_blendshapes": False,
    "import_guide": True,
    "import_proxy": True,
    "import_render": True,
    "import_visible_only": False,
    "import_usd_preview": False,
    "create_world_material": False,
    "apply_unit_conversion_scale": False,
}


class Markers:
    def __init__(self, path: Path, settle: float) -> None:
        self._file = path.open("w", encoding="utf-8")
        self._settle = settle

    def mark(self, name: str, **extra: Any) -> None:
        record = {
            "name": name,
            "t": time.monotonic(),
            "cpu": time.process_time(),
            "heap": memory.heap_in_use(),
            **memory.own_peaks(),
            **extra,
        }
        self._file.write(json.dumps(record) + "\n")
        self._file.flush()

    def settle(self, name: str) -> None:
        """A window at rest after a full collection; the parent reads memory over it."""
        gc.collect()
        self.mark(f"settle:{name}")
        time.sleep(self._settle)
        self.mark(f"settled:{name}")


def blender_counts() -> dict[str, Any]:
    """What the run built, so the two sides' work can be compared next to their numbers."""
    meshes = list(bpy.data.meshes)
    objects = list(bpy.data.objects)
    return {
        "objects": len(objects),
        "objects by type": dict(Counter(obj.type for obj in objects)),
        "collection instances": sum(1 for obj in objects if obj.instance_type == "COLLECTION"),
        "meshes": len(meshes),
        "vertices": sum(len(mesh.vertices) for mesh in meshes),
        "corners": sum(len(mesh.loops) for mesh in meshes),
        "faces": sum(len(mesh.polygons) for mesh in meshes),
        "materials": len(bpy.data.materials),
        "shader nodes": sum(len(m.node_tree.nodes) for m in bpy.data.materials if m.node_tree),
        "collections": len(bpy.data.collections),
        "modifiers": dict(Counter(mod.type for obj in objects for mod in obj.modifiers)),
        "constraints": dict(Counter(con.type for obj in objects for con in obj.constraints)),
        "images": len(bpy.data.images),
        "cache files": len(bpy.data.cache_files),
    }


def delete_blender_data() -> None:
    for collection in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.collections):
        bpy.data.batch_remove(list(collection))
    for collection in (
        bpy.data.node_groups,
        bpy.data.images,
        bpy.data.curves,
        bpy.data.lights,
        bpy.data.cameras,
        # The importer's Mesh Sequence Cache and Transform Cache read USD through these, which keep a reader open.
        bpy.data.cache_files,
    ):
        bpy.data.batch_remove(list(collection))
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    # The depsgraph keeps its evaluated copies until it next evaluates (measured: about 1.7 GB of live heap
    # after deleting ALab's imported data, 27 MB after an update).
    evaluate()


def evaluate() -> None:
    """The first depsgraph evaluation: the importer's cache modifiers and constraints read USD here."""
    view_layer: Any = bpy.context.view_layer
    view_layer.update()


def run_importer(config: dict[str, Any], markers: Markers) -> dict[str, Any]:
    options = {
        "importer-defaults": {},
        "importer-matched": MATCHED,
        "importer-expanded": {**MATCHED, "support_scene_instancing": False},
    }[config["mode"]]
    markers.settle("baseline")
    markers.mark("begin:import")
    importer: Any = bpy.ops.wm.usd_import  # the options are checked by name at run time
    result = importer(filepath=config["scene"], **options)
    markers.mark("end:import")
    markers.mark("begin:evaluate")
    evaluate()
    markers.mark("end:evaluate")
    counts = blender_counts()
    markers.settle("synced")
    markers.mark("begin:delete data")
    delete_blender_data()
    markers.mark("end:delete data")
    markers.settle("data deleted")
    return {"operator": sorted(result), "options": options, "blender": counts}


def run_prototype(config: dict[str, Any], markers: Markers) -> dict[str, Any]:
    sys.path.insert(0, config["module_dir"])
    import _hydra_bridge as native  # ty: ignore[unresolved-import] - built into build/hydra-bridge
    import apply
    from pxr import Usd

    native.take_filter_timings()
    markers.settle("baseline")
    filter_timings: dict[str, Any] = {}

    def stage(name: str) -> None:
        markers.mark(f"begin:{name}")

    def done(name: str) -> None:
        markers.mark(f"end:{name}")
        filter_timings[name] = {kind: list(value) for kind, value in native.take_filter_timings().items()}

    stage("stage open")
    usd_stage = Usd.Stage.Open(config["scene"], Usd.Stage.LoadAll)
    done("stage open")
    stage("bridge construction")
    bridge = native.Bridge(usd_stage)
    done("bridge construction")
    stage("capture")
    snapshot = bridge.capture(config["time"])
    done("capture")
    stage("planning")
    plan = native.build_plan(snapshot)
    done("planning")
    stage("transfer")
    view = SimpleNamespace(materials=plan.materials, meshes=plan.meshes, objects=plan.objects)
    done("transfer")
    stage("construction")
    collection = bpy.data.collections.new("Prototype")
    scene: Any = bpy.context.scene
    scene.collection.children.link(collection)
    apply.apply(view, collection)
    done("construction")
    stage("evaluate")
    evaluate()
    done("evaluate")
    facts = {
        "snapshot prims": len(snapshot.paths()),
        "plan meshes": len(view.meshes),
        "plan objects": len(view.objects),
        "plan materials": len(view.materials),
        "placeholders": dict(Counter(o["placeholder_type"] for o in view.objects if o["placeholder_type"])),
        "plan positions": sum(len(m["positions"]) for m in view.meshes),
        "diagnostics": len(plan.diagnostics),
        "diagnostic codes": dict(Counter(d["code"] for d in plan.diagnostics)),
    }
    counts = blender_counts()
    markers.settle("synced")
    stage("release")
    bridge.release()
    del bridge, snapshot, plan, view
    done("release")
    markers.settle("bridge released")
    stage("drop stage")
    del usd_stage
    done("drop stage")
    markers.settle("stage dropped")
    stage("delete data")
    delete_blender_data()
    done("delete data")
    markers.settle("data deleted")
    return {"plan": facts, "blender": counts, "filter timings": filter_timings}


def main(config_path: Path) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    # An empty scene, so counts and deletion cover only what the run imports.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene: Any = bpy.context.scene
    scene.frame_set(int(config["time"]))
    markers = Markers(Path(config["markers"]), config["settle"])
    markers.mark("ready")
    run = run_importer if config["mode"].startswith("importer") else run_prototype
    result = run(config, markers)
    result["blender version"] = bpy.app.version_string
    result["build hash"] = bpy.app.build_hash.decode()
    Path(config["result"]).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[sys.argv.index("--") + 1]))
