"""One measured synchronization in the Blender binary: Blender's USD importer, or the Hydra prototype.

    blender --background --factory-startup --python child.py -- <config.json>

The config names the mode, scene, time code, module directory, and output paths. An update mode (M4 Phase C)
runs one of scenarios.py's scenarios after the prototype's synchronization: its edit, then the capture,
planning, diff, and update that follow; the initial scenario saves the .blend instead. The interaction mode
times the interaction functions after it (interaction_timing.py), and the ownership mode the first ownership
lookup after an undo, the display written as a binding's manifest (ownership_timing.py). The child writes a marker
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
import interaction_timing  # noqa: E402
import memory  # noqa: E402
import ownership_timing  # noqa: E402
import scenarios  # noqa: E402

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
    import batch
    from pxr import Usd

    # The baseline's one object per copy (apply.py), or Phase D's batched display (batch.py).
    batched = config.get("representation", "objects") == "batched"
    if batched and config["mode"] == "ownership":
        raise SystemExit("ownership mode measures the baseline's manifest only")

    native.take_filter_timings()
    markers.settle("baseline")
    filter_timings: dict[str, Any] = {}

    def stage(name: str) -> None:
        markers.mark(f"begin:{name}")

    def done(name: str) -> None:
        markers.mark(f"end:{name}")
        filter_timings[name] = {kind: list(value) for kind, value in native.take_filter_timings().items()}

    scenario = config.get("scenario")
    stage("stage open")
    usd_stage = Usd.Stage.Open(config["scene"], scenarios.load_set(scenario or "initial"))
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
    scene: Any = bpy.context.scene
    binding_id = None
    if config["mode"] == "ownership":
        # The display goes into a file binding's destination, made through M3's API, whose manifest C5 writes.
        sys.path.insert(0, str(HERE.parents[3] / "src"))
        import proscenium
        from proscenium import runtime
        from proscenium.api.bindings import BINDINGS

        proscenium.register()
        binding_id = BINDINGS.create_file_binding(scene, config["scene"], name="Prototype").binding_id
        found = runtime.find_binding(binding_id)
        assert found is not None and found.config is not None and found.config.destination is not None
        collection = found.config.destination
    else:
        collection = bpy.data.collections.new("Prototype")
        scene.collection.children.link(collection)
    display: Any = (
        batch.apply_batched(view, collection, config.get("batch_minimum", batch.MINIMUM))
        if batched
        else apply.apply(view, collection)
    )
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
    if batched:
        facts |= {
            "batches": len(display.batches),
            "instances": sum(len(b.elements) for b in display.batches),
            "plan objects kept as objects": len(display.objects),
        }
    counts = blender_counts()
    markers.settle("synced")
    if scenario == "initial":
        blend = Path(config["work"]) / "synced.blend"
        stage("save")
        bpy.ops.wm.save_as_mainfile(filepath=str(blend), compress=False)
        done("save")
        facts["blend bytes"] = blend.stat().st_size
    elif config["mode"] == "ownership":
        facts["ownership"] = ownership_timing.measure(binding_id, display, view.objects, view.materials)
    elif config["mode"] == "interaction":
        import batch_selection
        import selection

        # The display component and what its functions take: the collection, or the batched display.
        facts["interaction"] = interaction_timing.measure(
            native,
            batch_selection if batched else selection,
            usd_stage,
            plan,
            display if batched else collection,
            config["time"],
        )
    elif scenario is not None:
        session = SimpleNamespace(
            stage=usd_stage, bridge=bridge, plan=plan, display=display, collection=collection, batched=batched
        )
        facts["update"] = run_update(scenario, config["time"], session, stage, done)
        markers.settle("updated")
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


def run_update(scenario: str, time: float, session: SimpleNamespace, stage: Any, done: Any) -> dict[str, Any]:
    """The scenario's edit, then the incremental capture, planning, diff, and update by the diff."""
    import _hydra_bridge as native  # ty: ignore[unresolved-import] - built into build/hydra-bridge
    import batch_update
    import update

    updater: Any = batch_update if session.batched else update
    stage("update:edit")
    capture_time, edited = scenarios.edit(scenario, session.stage, session.plan, time)
    done("update:edit")
    stage("update:capture")
    snapshot = session.bridge.capture(capture_time, incremental=True)
    done("update:capture")
    stage("update:planning")
    plan = native.build_plan(snapshot)
    done("update:planning")
    stage("update:diff")
    diff = native.diff_plans(session.plan, plan)
    done("update:diff")
    stage("update:prepare")
    prepared = updater.prepare(plan, diff, session.display, update.UserPolicy.REPOINT)
    done("update:prepare")
    stage("update:publish")
    updater.publish(prepared, session.display, session.collection)
    done("update:publish")
    stage("update:retire")
    retired = len(prepared.retired)
    kept = updater.retire(prepared)
    done("update:retire")
    stage("update:evaluate")
    evaluate()
    done("update:evaluate")
    return {
        "edited": edited,
        "copied prims": snapshot.copied,
        "diff": {
            "changed": len(diff["changed"]),
            "repointable": len(diff["repointable"]),
            "added": diff["objects"].count(-1),
            "removed": len(diff["removed"]),
            "new meshes": diff["meshes"].count(-1),
            "new materials": diff["materials"].count(-1),
        },
        "written": {
            "created": len(prepared.created),
            "repointed": len(prepared.repointed),
            "renumbered": len(prepared.renumbered),
            "retired": retired,
            "kept for other users": len(kept),
        }
        | (_batches_written(prepared) if session.batched else {}),
        "blender": blender_counts(),
    }


def _batches_written(prepared: Any) -> dict[str, int]:
    """What a batched update wrote to its batches."""
    return {
        "batches added": len(prepared.added),
        "batches dropped": len(prepared.dropped),
        "points rebuilt": sum(rebatch.points is not None for rebatch in prepared.kept),
        "prototypes repointed": sum(rebatch.reprototyped for rebatch in prepared.kept),
        "points renumbered": sum(rebatch.renumbered for rebatch in prepared.kept),
    }


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
