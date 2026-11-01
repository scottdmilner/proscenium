"""Isolated body: M4 Phase E, time-sampled data: the bridge's cached display (cached.py, E3).

Runs in a fresh process (isolated/harness.py); see tests/isolated/test_cached.py.
"""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy
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
) -> dict[str, Any]:
    """Build a cached display of frames.usda at `start`, without Morph, and visit each of `visits` by `frame_set`.

    A visit's fraction is its subframe, which the display synchronizes at only with `subframes`. Then edit Still's
    points and visit each of `edited_visits`. Each visit reports whether it synchronized, whether that rebuilt the
    display, and where the display differs from a fresh plan at the time it shows: the visit's, or with no
    `subframes`, its frame's.
    """
    sys.path[:0] = [str(BRIDGE), module_dir]
    native = importlib.import_module("_hydra_bridge")
    cached = importlib.import_module("cached")
    stage = _stage(dest)
    stage.GetPrimAtPath("/World/Morph").SetActive(False)  # its topology varies, which E4 caches
    collection = bpy.data.collections.new("Cached")
    scene: Any = bpy.context.scene  # never None in a running Blender
    scene.collection.children.link(collection)
    scene.frame_set(int(start), subframe=start % 1)
    display = cached.CachedDisplay(native, stage, collection, start, predict=predict)
    handler = display.follow(scene, subframes)
    result: dict[str, Any] = {"visits": []}
    try:
        for time in visits:
            result["visits"].append(_visit(native, stage, display, scene, time, subframes))
        result["split"] = sum(s.split for s in display.synchronized)
        result["predicted"] = _copies(display.predicted)
        result["confirmed"] = _copies(display.confirmed())
        result["cached"] = sorted(display.cached)
        points = UsdGeom.Mesh(stage.GetPrimAtPath("/World/Still")).GetPointsAttr()
        points.Set([(6, 0, 1), (7, 0, 1), (6, 1, 1)])
        result["edited"] = display.edited
        result["edited_visits"] = [_visit(native, stage, display, scene, t, subframes) for t in edited_visits]
    finally:
        bpy.app.handlers.frame_change_pre.remove(handler)
        display.release()
    return result


def uncached(module_dir: str, dest: str) -> str:
    """The error synchronizing frames.usda at 3 raises after building it at 1, where Morph gains a face."""
    sys.path[:0] = [str(BRIDGE), module_dir]
    native = importlib.import_module("_hydra_bridge")
    cached = importlib.import_module("cached")
    stage = _stage(dest)
    collection = bpy.data.collections.new("Cached")
    display = cached.CachedDisplay(native, stage, collection, 1.0)
    try:
        display.synchronize(3.0)
    except cached.UncachedError as error:
        return str(error)
    finally:
        display.release()
    return ""


def blended(module_dir: str, dest: str, synchronized: list[float], shown: list[float]) -> dict[str, Any]:
    """Synchronize a blending cached display of frames.usda at `synchronized`, then show each of `shown`.

    The display is built at the first, without Morph, and follows `frame_set` without `subframes`, so a shown
    time isn't synchronized. At each shown time, between cached time codes a and b, reports where the display
    differs from fresh plans at a and b: a viewport object's float mesh attributes mixed linearly by the time
    between a and b, its integer ones and its transform as at a.
    """
    sys.path[:0] = [str(BRIDGE), module_dir]
    native = importlib.import_module("_hydra_bridge")
    cached = importlib.import_module("cached")
    apply = importlib.import_module("apply")
    frames = importlib.import_module("frames")
    stage = _stage(dest)
    stage.GetPrimAtPath("/World/Morph").SetActive(False)  # its topology varies, which E4 caches
    collection = bpy.data.collections.new("Cached")
    scene: Any = bpy.context.scene  # never None in a running Blender
    scene.collection.children.link(collection)
    scene.frame_set(int(synchronized[0]))
    display = cached.CachedDisplay(native, stage, collection, synchronized[0], blend=True)
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
        for time in shown:
            scene.frame_set(int(time), subframe=time % 1)
            a = max(t for t in display.cached if t <= time)
            b = min((t for t in display.cached if t > time), default=a)
            weight = 0.0 if b == a else (time - a) / (b - a)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            found = []
            for key, (record, layers) in fresh(a).items():
                obj = display.objects[key]
                if not record["viewport"] or not layers:
                    continue
                expected = apply.world(record["matrix"])
                basis = obj.matrix_basis if obj.parent is None else obj.parent.matrix_basis @ obj.matrix_basis
                if max(abs(basis[r][c] - expected[r][c]) for r in range(4) for c in range(4)) > TOLERANCE:
                    found.append(f"{key}: transform")
                after = dict((layer.name, layer) for layer in fresh(b)[key][1])
                geometry = obj.evaluated_get(depsgraph).evaluated_geometry()  # read while referenced
                for layer in layers:
                    values = numpy.empty_like(layer.values)
                    geometry.mesh.attributes[layer.name].data.foreach_get(layer.prop, values)
                    mixed = layer.values
                    if layer.data_type != "INT":
                        mixed = (1 - weight) * layer.values + weight * after[layer.name].values
                    if not numpy.allclose(values, mixed, atol=TOLERANCE):
                        found.append(f"{key}: {layer.name}")
            visits.append({"time": time, "between": [a, b], "mismatches": found})
        return {"visits": visits, "synchronized": [s.time for s in display.synchronized[count:]]}
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
    """Where the display, as Blender evaluates it now, differs from a fresh plan at `time`."""
    apply = importlib.import_module("apply")
    frames = importlib.import_module("frames")
    bridge = native.Bridge(stage)
    plan = native.build_plan(bridge.capture(time))
    bridge.release()
    records = dict(enumerate(plan.objects))
    fresh = {(*frames.copy_of(r), frames.place(i, records, {})): r for i, r in records.items()}
    found = [f"{key}: no object" for key in fresh.keys() - display.objects.keys()]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for key, obj in display.objects.items():
        record = fresh.get(key)
        shown = (False, False) if record is None else (record["viewport"], record["render"])
        if (not obj.hide_viewport, not obj.hide_render) != shown:
            found.append(f"{key}: shown {(not obj.hide_viewport, not obj.hide_render)}, not {shown}")
        if record is None or not any(shown):
            continue
        basis = obj.matrix_basis if obj.parent is None else obj.parent.matrix_basis @ obj.matrix_basis
        expected = apply.world(record["matrix"])
        if max(abs(basis[r][c] - expected[r][c]) for r in range(4) for c in range(4)) > TOLERANCE:
            found.append(f"{key}: transform")
        expected_color = apply.object_color(record)
        if any(abs(a - b) > TOLERANCE for a, b in zip(obj.color, expected_color, strict=True)):
            found.append(f"{key}: color {tuple(obj.color)}, not {expected_color}")
        for name, value in record["properties"].items():
            if not numpy.allclose(numpy.array(_plain(obj[name]), float), numpy.array(value, float)):
                found.append(f"{key}: property {name}")
        names = [None if m is None else plan.materials[m]["name"] for m in record["material_slots"]]
        held = [None if s.material is None else s.material.name for s in obj.material_slots]
        if held != names:
            found.append(f"{key}: materials {held}, not {names}")
        if shown[0]:  # Blender evaluates the viewport's objects only
            found += _content_mismatches(apply, key, obj.evaluated_get(depsgraph), record, plan)
    return found


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
        except (AttributeError, RuntimeError):  # missing, or of another size
            found.append(f"{key}: no {layer.name} of its size")
            continue
        if not numpy.array_equal(values, layer.values):
            found.append(f"{key}: {layer.name}")
    leftover = [a.name for a in mesh.attributes if "@" in a.name]
    if leftover:
        found.append(f"{key}: frame attributes {leftover}")
    return found


def _plain(value: Any) -> Any:
    return [_plain(v) for v in value] if hasattr(value, "__len__") and not isinstance(value, str) else value
