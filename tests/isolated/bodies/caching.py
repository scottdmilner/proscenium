"""Isolated body: M4 Phase E, time-sampled data: the bridge's cached display (cached.py, E3 and E4).

Runs in a fresh process (isolated/harness.py); see tests/isolated/test_cached.py.
"""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy
import mathutils
import numpy
from pxr import Usd, UsdGeom

BRIDGE = Path(__file__).resolve().parents[3] / "tools/feasibility/hydra_bridge"
SCENES = ("animation.usda", "frames.usda")  # frames.usda sublayers M1b's animation case
TOLERANCE = 1e-5


def follow(  # noqa: PLR0913 - the scene, the times visited, and the display's options
    module_dir: str,
    dest: str,
    start: float,
    visits: list[float],
    predict: bool,
    edited_visits: list[float],
    subframes: bool = False,
    minimum: int | None = None,
) -> dict[str, Any]:
    """Build a cached display of frames.usda at `start`, batched with `minimum`, and visit each of `visits`.

    Visits are by `frame_set`.
    A visit's fraction is its subframe, which the display synchronizes at only with `subframes`. Then edit Still's
    points and visit each of `edited_visits`.
    Each visit reports whether it synchronized, whether that rebuilt the display, and where the display differs
    from a fresh plan at the time it shows: the visit's, or with no `subframes`, its frame's.
    """
    sys.path[:0] = [str(BRIDGE), module_dir]
    native = importlib.import_module("_hydra_bridge")
    cached = importlib.import_module("cached")
    stage = _stage(dest)
    collection = bpy.data.collections.new("Cached")
    scene: Any = bpy.context.scene  # never None in a running Blender
    scene.collection.children.link(collection)
    scene.frame_set(int(start), subframe=start % 1)
    display = cached.CachedDisplay(native, stage, collection, start, predict=predict, minimum=minimum)
    handler = display.follow(scene, subframes)
    result: dict[str, Any] = {"visits": []}
    try:
        for time in visits:
            result["visits"].append(_visit(native, stage, display, scene, time, subframes))
        result["split"] = sum(s.split for s in display.synchronized)
        result["predicted"] = _copies(display.predicted)
        result["confirmed"] = _copies(display.confirmed())
        result["cached"] = sorted(display.cached)
        result["whole"] = _whole(display)
        result["batched"] = _batched(display)
        points = UsdGeom.Mesh(stage.GetPrimAtPath("/World/Still")).GetPointsAttr()
        points.Set([(6, 0, 1), (7, 0, 1), (6, 1, 1)])
        result["edited"] = display.edited
        result["edited_visits"] = [_visit(native, stage, display, scene, t, subframes) for t in edited_visits]
    finally:
        bpy.app.handlers.frame_change_pre.remove(handler)
        display.release()
    return result


def _unresolved(display: Any) -> list[str]:
    """The display's objects' keyed paths that resolve to nothing."""
    found = []
    holders = list(display.objects.items())
    if display.batches is not None:
        holders += [(b.key, o) for b in display.batches.batches for o in (b.prototype, b.carrier)]
    for key, obj in holders:
        action = obj.animation_data.action if obj.animation_data else None
        for curve in action.layers[0].strips[0].channelbags[0].fcurves if action and action.layers else []:
            try:
                obj.path_resolve(curve.data_path)
            except ValueError:
                found.append(f"{key[0]}: {curve.data_path}")
    return sorted(found)


def _whole(display: Any) -> list[str]:
    """The sources of the tracks whose holders' meshes cache whole meshes, sorted."""
    holders = [(key, obj) for key, obj in display.objects.items()]
    if display.batches is not None:
        holders += [
            (key, b.prototype) for b in display.batches.batches for key in b.tracks if key in display.batches.held
        ]
    return sorted(
        {
            key[0]
            for key, obj in holders
            if obj.data is not None and getattr(display.meshes.caches.get(obj.data.session_uid), "whole", None)
        }
    )


def _batched(display: Any) -> list[dict[str, Any]]:
    """Each batch: its tracks, [source, context, whether it still holds it], and its points' varying attributes.

    A track it no longer holds says too whether its object shares the batch's prototype's mesh. Sorted, as plan
    order varies by process.
    """
    if display.batches is None:
        return []
    held = display.batches.held
    found = []
    for batch in display.batches.batches:
        tracks = []
        for key in batch.tracks:
            track = [key[0], list(key[1]), key in held]
            if key not in held:
                track.append(display.objects[key].data == batch.prototype.data)
            tracks.append(track)
        varying = sorted(batch.cache.varying) if batch.cache else []
        found.append({"tracks": sorted(tracks), "varying": varying})
    return sorted(found, key=lambda b: b["tracks"])


def blended(
    module_dir: str, dest: str, synchronized: list[float], shown: list[float], minimum: int | None = None
) -> dict[str, Any]:
    """Synchronize a blending cached display of frames.usda at `synchronized`, then show each of `shown`.

    With `minimum`, the display is batched.

    The display is built at the first, and follows `frame_set` without `subframes`, so a shown time isn't
    synchronized. At each shown time, between cached time codes a and b, reports where the display differs from
    fresh plans at a and b: a viewport object's float mesh attributes mixed linearly by the time between a and b,
    its integer ones and its transform as at a, and a mesh cached whole as at a.
    """
    sys.path[:0] = [str(BRIDGE), module_dir]
    native = importlib.import_module("_hydra_bridge")
    cached = importlib.import_module("cached")
    apply = importlib.import_module("apply")
    frames = importlib.import_module("frames")
    stage = _stage(dest)
    collection = bpy.data.collections.new("Cached")
    scene: Any = bpy.context.scene  # never None in a running Blender
    scene.collection.children.link(collection)
    scene.frame_set(int(synchronized[0]))
    display = cached.CachedDisplay(native, stage, collection, synchronized[0], blend=True, minimum=minimum)
    handler = display.follow(scene)
    plans: dict[float, dict[Any, tuple[Any, Any]]] = {}

    def fresh(time: float) -> dict[Any, tuple[Any, Any]]:  # by track: its record and its mesh's layers
        if time not in plans:
            bridge = native.Bridge(stage)
            plan = native.build_plan(bridge.capture(time))
            bridge.release()
            records = dict(enumerate(plan.objects))
            plans[time] = {
                (*frames.copy_of(r), frames.place(i, records, {})): (r, _layers(apply, plan, r))
                for i, r in records.items()
            }
        return plans[time]

    visits = []
    try:
        for time in synchronized[1:]:
            scene.frame_set(int(time))
        count = len(display.synchronized)
        whole = set(_whole(display))
        for time in shown:
            scene.frame_set(int(time), subframe=time % 1)
            a = max(t for t in display.cached if t <= time)
            b = min((t for t in display.cached if t > time), default=a)
            weight = 0.0 if b == a else (time - a) / (b - a)
            holders = _holders(display)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            found = []
            for key, (record, layers) in fresh(a).items():
                showing = [h for h in holders.get(key, []) if h["viewport"]]
                if not record["viewport"] or not layers:
                    continue
                if not showing:
                    found.append(f"{key}: not shown")
                    continue
                if _moved(showing[0], record):
                    found.append(f"{key}: transform")
                # A track absent at b shows a's values: an absent track's object holds its mesh's own.
                after = dict((layer.name, layer) for layer in fresh(b).get(key, fresh(a)[key])[1])
                geometry = showing[0]["object"].evaluated_get(depsgraph).evaluated_geometry()  # read while referenced
                for layer in layers:
                    values = numpy.empty_like(layer.values)
                    try:
                        geometry.mesh.attributes[layer.name].data.foreach_get(layer.prop, values)
                    except (RuntimeError, TypeError):  # of another size
                        found.append(f"{key}: no {layer.name} of its size")
                        continue
                    if layer.name not in after:
                        continue  # nothing to mix toward, as for a held display color b's mesh lacks (D13)
                    mixed = layer.values
                    if layer.data_type != "INT" and key[0] not in whole:
                        mixed = (1 - weight) * layer.values + weight * after[layer.name].values
                    if not numpy.allclose(values, mixed, atol=TOLERANCE):
                        found.append(f"{key}: {layer.name}")
            visits.append({"time": time, "between": [a, b], "mismatches": found})
        return {
            "visits": visits,
            "synchronized": [s.time for s in display.synchronized[count:]],
            "whole": sorted(whole),
            "unresolved": _unresolved(display),
        }
    finally:
        bpy.app.handlers.frame_change_pre.remove(handler)
        display.release()


def _layers(apply: Any, plan: Any, record: Any) -> list[Any]:
    """An object's mesh layers as apply holds them, or its placeholder bounds as corners; empty for neither."""
    if record["mesh"] is not None:
        return apply.layers(plan.meshes_at([record["mesh"]])[0])
    if record["bounds"] is None:
        return []
    low, high = record["bounds"]
    corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
    return [apply.Layer("position", "FLOAT_VECTOR", "POINT", "vector", numpy.array(corners, "f").ravel())]


def predicting(module_dir: str, dest: str, time: float, later: float) -> dict[str, Any]:
    """A capture of frames.usda at `time` with its time dependencies, against one without, on bridges of their own.

    Reports whether their plans' objects are equal but for their dirtied aspects, each plan's dirtied aspects by
    copy, those of a plan at `later` after the plain capture, and whether a capture at `later` after each dirties
    the same locators of the same prims.
    """
    sys.path[:0] = [str(BRIDGE), module_dir]
    native = importlib.import_module("_hydra_bridge")
    stage = _stage(dest)
    plans, dirtied_locators, later_plans = [], [], []
    for dependencies in (True, False):
        bridge = native.Bridge(stage)
        plan = native.build_plan(bridge.capture(time, time_dependencies=dependencies))
        plans.append(plan.objects)
        snapshot = bridge.capture(later, incremental=True)
        dirtied_locators.append({path: sorted(set(locators)) for path, locators in snapshot.dirty_locators.items()})
        later_plans.append(native.build_plan(snapshot, previous=plan).objects)
        bridge.release()
    rest = [[{k: v for k, v in r.items() if k != "dirtied_aspects"} for r in objects] for objects in plans]
    return {
        "same_plan": rest[0] == rest[1],
        "dirtied_aspects": _copies(_dirtied_aspects(plans[0])),
        "plain_dirtied_aspects": _copies(_dirtied_aspects(plans[1])),
        "later_dirtied_aspects": _copies(_dirtied_aspects(later_plans[1])),
        "same_dirtied_locators": dirtied_locators[0] == dirtied_locators[1],
    }


def _dirtied_aspects(objects: list[Any]) -> dict[tuple[str, tuple[str, ...]], set[str]]:
    aspects: dict[tuple[str, tuple[str, ...]], set[str]] = {}
    for record in objects:
        aspects.setdefault((record["source"], tuple(record["instance_context"])), set()).update(
            record["dirtied_aspects"]
        )
    return aspects


def _stage(dest: str) -> Usd.Stage:
    for name in SCENES:
        shutil.copy(BRIDGE / "cases" / name, dest)
    stage = Usd.Stage.Open(str(Path(dest) / "frames.usda"))
    stage.SetEditTarget(stage.GetSessionLayer())
    return stage


def _copies(aspects: dict[tuple[str, tuple[str, ...]], set[str]]) -> list[list[Any]]:
    return sorted([source, list(context), sorted(found)] for (source, context), found in aspects.items() if found)


def _visit(  # noqa: PLR0913 - the display and the time visited
    native: Any, stage: Usd.Stage, display: Any, scene: Any, time: float, subframes: bool
) -> dict[str, Any]:
    count = len(display.synchronized)
    scene.frame_set(int(time), subframe=time % 1)
    synchronized = display.synchronized[count:]
    return {
        "time": time,
        "synchronized": [s.time for s in synchronized],
        "rebuilt": [s.rebuilt for s in synchronized],
        "mismatches": _mismatches(native, stage, display, time if subframes else float(int(time))),
    }


def _mismatches(native: Any, stage: Usd.Stage, display: Any, time: float) -> list[str]:
    """Where the display, as Blender evaluates it now, differs from a fresh plan at `time`.

    Each track is shown by one of its holders, an object or a batch's point, which holds what its record does, and
    by no other.
    """
    apply = importlib.import_module("apply")
    frames = importlib.import_module("frames")
    bridge = native.Bridge(stage)
    plan = native.build_plan(bridge.capture(time))
    bridge.release()
    records = dict(enumerate(plan.objects))
    fresh = {(*frames.copy_of(r), frames.place(i, records, {})): r for i, r in records.items()}
    holders = _holders(display)
    found = [f"{key}: no object" for key in fresh.keys() - holders.keys()]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for key, held in holders.items():
        record = fresh.get(key)
        expected = (False, False) if record is None else (record["viewport"], record["render"])
        showing = [h for h in held if h["viewport"] or h["render"]]
        if len(showing) > 1:
            found.append(f"{key}: shown by {len(showing)} holders")
        shown = (showing[0]["viewport"], showing[0]["render"]) if showing else (False, False)
        if shown != expected:
            found.append(f"{key}: shown {shown}, not {expected}")
        if record is None or not showing:
            continue
        holder = showing[0]
        if _moved(holder, record):
            found.append(f"{key}: transform")
        expected_color = apply.object_color(record)
        if any(abs(a - b) > TOLERANCE for a, b in zip(holder["color"], expected_color, strict=True)):
            found.append(f"{key}: color {tuple(holder['color'])}, not {expected_color}")
        for name, value in record["properties"].items():
            if not numpy.allclose(numpy.array(holder["properties"](name), float), numpy.array(value, float)):
                found.append(f"{key}: property {name}")
        # By their sources, as Blender renames materials of the same name.
        sources = [None if m is None else list(plan.materials[m]["sources"]) for m in record["material_slots"]]
        if holder["materials"] != sources:
            found.append(f"{key}: materials {holder['materials']}, not {sources}")
        if shown[0]:  # Blender evaluates the viewport's objects only
            evaluated = holder["object"].evaluated_get(depsgraph)
            found += _content_mismatches(apply, key, evaluated, record, plan)
            found += _topology_mismatches(key, evaluated, record, plan)
    return found


def _moved(holder: dict[str, Any], record: Any) -> bool:
    """Whether a holder's transform, or its instance's, differs from its record's.

    Blender holds matrices in single precision, so the tolerance grows with the matrix's largest value.
    """
    expected = numpy.array(record["matrix"], float).ravel()
    tolerance = TOLERANCE * max(1.0, float(numpy.abs(expected).max()))
    matrices = [m for m in (holder["matrix"], holder.get("instance")) if m is not None]
    return any(numpy.abs(numpy.array(m) - expected).max() > tolerance for m in matrices)


def _holders(display: Any) -> dict[Any, list[dict[str, Any]]]:
    """By track, what each of its holders shows: an object, or a batch's point, which its batch instances."""
    found: dict[Any, list[dict[str, Any]]] = {}
    for key, obj in display.objects.items():
        basis = _basis(obj) if obj.parent is None else _basis(obj.parent) @ _basis(obj)
        found.setdefault(key, []).append(
            {
                "viewport": not obj.hide_viewport,
                "render": not obj.hide_render,
                "matrix": _usd(basis),
                "color": tuple(obj.color),
                "properties": lambda name, obj=obj: _plain(obj[name]),
                "materials": _sources(obj),
                "object": obj,
            }
        )
    if display.batches is None:
        return found
    batches = importlib.import_module("cached_batches")
    view_layer: Any = bpy.context.view_layer  # never None in a running Blender
    # The points as the carrier's frames modifier gives them, before its batch modifier instances them.
    modifiers = [b.carrier.modifiers[batches.MODIFIER] for b in display.batches.batches]
    for modifier in modifiers:
        modifier.show_viewport = False
    view_layer.update()
    points = [_point_values(b.carrier.evaluated_get(view_layer.depsgraph)) for b in display.batches.batches]
    for modifier in modifiers:
        modifier.show_viewport = True
    view_layer.update()
    instances: dict[str, dict[int, Any]] = {}  # by carrier, its instances' world matrices in instance order
    for instance in view_layer.depsgraph.object_instances:
        if instance.is_instance and instance.parent:
            # The instance's index in its carrier's instances is persistent_id[1] (ad hoc, Blender 5.2); its
            # matrix is valid only while the iteration is at it.
            drawn = instances.setdefault(instance.parent.original.name, {})
            drawn[instance.persistent_id[1]] = instance.matrix_world.copy()
    for batch, values in zip(display.batches.batches, points, strict=True):
        prototype = batch.prototype
        # The carrier instances the points shown in the viewport, in point order.
        drawn = [m for _, m in sorted(instances.get(batch.carrier.name, {}).items())]
        shown = [point for point in range(len(batch.tracks)) if values[batches.VIEWPORT][point]]
        placed = dict(zip(shown, drawn, strict=False))
        for point, key in enumerate(batch.tracks):
            viewport = bool(values[batches.VIEWPORT][point])
            found.setdefault(key, []).append(
                {
                    # Shown in the viewport only when the carrier instances it, as many times as it has points so.
                    "viewport": viewport and point in placed and len(drawn) == len(shown),
                    "render": bool(values[batches.RENDER][point]),
                    "matrix": values["proscenium_transform"][point],
                    "instance": _usd(placed.get(point)),
                    "color": tuple(prototype.color),
                    "properties": lambda name, values=values, point=point: values[name][point],
                    "materials": _sources(prototype),
                    "object": prototype,
                }
            )
    return found


def _basis(obj: Any) -> Any:
    """An object's transform as its keys give it now, which the viewport evaluates only for objects it shows."""
    action = obj.animation_data.action if obj.animation_data else None
    curves: Any = action.layers[0].strips[0].channelbags[0].fcurves if action and action.layers else None
    if not obj.hide_viewport or curves is None or curves.find("location", index=0) is None:
        return obj.matrix_basis
    scene: Any = bpy.context.scene  # never None in a running Blender
    time = scene.frame_current + scene.frame_subframe

    def keyed(path: str) -> list[float]:
        return [curves.find(path, index=i).evaluate(time) for i in range(3)]

    return mathutils.Matrix.LocRotScale(keyed("location"), mathutils.Euler(keyed("rotation_euler")), keyed("scale"))


def _sources(obj: Any) -> list[list[str] | None]:
    """The sources of the material in each of an object's slots."""
    return [None if s.material is None else list(s.material["proscenium_sources"]) for s in obj.material_slots]


def _point_values(evaluated: Any) -> dict[str, list[Any]]:
    """An evaluated points mesh's attributes, per point: a matrix's 16 values, a vector's components."""
    geometry = evaluated.evaluated_geometry()  # its mesh is read while this is referenced
    mesh = geometry.mesh
    found = {}
    for attribute in mesh.attributes:
        if attribute.domain != "POINT" or attribute.name.startswith("."):
            continue
        prop = "vector" if attribute.data_type in ("FLOAT_VECTOR", "FLOAT2") else "value"
        width = {"FLOAT4X4": 16, "FLOAT_VECTOR": 3, "FLOAT2": 2}.get(attribute.data_type, 1)
        dtype = bool if attribute.data_type == "BOOLEAN" else int if attribute.data_type == "INT" else numpy.float32
        values = numpy.empty(len(mesh.vertices) * width, dtype)
        attribute.data.foreach_get(prop, values)
        rows = values.reshape(len(mesh.vertices), width)
        found[attribute.name] = [list(row) if width > 1 else row[0] for row in rows.tolist()]
    return found


def _usd(matrix: Any) -> list[float] | None:
    """A Blender matrix as USD's row-vector matrix, flattened row by row."""
    return None if matrix is None else [matrix[c][r] for r in range(4) for c in range(4)]


def _content_mismatches(apply: Any, key: Any, evaluated: Any, record: Any, plan: Any) -> list[str]:
    if record["mesh"] is not None:
        expected = apply.layers(plan.meshes_at([record["mesh"]])[0])
    elif record["bounds"] is not None:
        low, high = record["bounds"]
        corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
        expected = [apply.Layer("position", "FLOAT_VECTOR", "POINT", "vector", numpy.array(corners, "f").ravel())]
    else:
        return []
    geometry = evaluated.evaluated_geometry()  # its mesh is read while this is referenced
    mesh = geometry.mesh
    found = []
    for layer in expected:
        attribute = mesh.attributes.get(layer.name)
        values = numpy.empty_like(layer.values)
        try:
            attribute.data.foreach_get(layer.prop, values)
        except (AttributeError, RuntimeError, TypeError):  # missing, or of another size
            found.append(f"{key}: no {layer.name} of its size")
            continue
        if not numpy.array_equal(values, layer.values):
            found.append(f"{key}: {layer.name}")
    leftover = [a.name for a in mesh.attributes if "@" in a.name]
    if leftover:
        found.append(f"{key}: frame attributes {leftover}")
    return found


def _topology_mismatches(key: Any, evaluated: Any, record: Any, plan: Any) -> list[str]:
    """Where an evaluated mesh's faces and corners differ from its plan mesh's."""
    if record["mesh"] is None:
        return []
    expected = plan.meshes_at([record["mesh"]])[0]
    geometry = evaluated.evaluated_geometry()  # its mesh is read while this is referenced
    mesh = geometry.mesh
    corners = numpy.empty(len(mesh.loops), numpy.int32)
    starts = numpy.empty(len(mesh.polygons), numpy.int32)
    if len(corners):
        mesh.attributes[".corner_vert"].data.foreach_get("value", corners)
    mesh.polygons.foreach_get("loop_start", starts)
    same = numpy.array_equal(corners, numpy.array(expected["corner_verts"], numpy.int32)) and numpy.array_equal(
        starts, numpy.array(expected["face_offsets"], numpy.int32)
    )
    return [] if same else [f"{key}: topology"]


def _plain(value: Any) -> Any:
    return [_plain(v) for v in value] if hasattr(value, "__len__") and not isinstance(value, str) else value
