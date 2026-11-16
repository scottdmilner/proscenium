"""A scene's source selection through Bindings: stored, resolved, mirrored, and changed by picks and boxes.

DECISIONS.md "Headless interaction functions". Expected values come from the interaction fixtures, and a box's from each
element's world bounds' center computed with USD's own APIs (UsdGeom.Boundable's extent, Imageable's local-to-world
transform), never from the display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest
from mathutils import Vector
from pxr import Gf, Usd, UsdGeom

from fixtures import interaction
from proscenium.api.bindings import PersistentSelection, SelectionEntry, SelectionMode
from proscenium.binding.results import ResultState
from proscenium.binding.source_access.binding_settings import PayloadPolicy
from support import interaction_oracle

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.api.bindings import BindingHandle, Bindings

CHAIR, TABLE = "/World/Props/Chair", "/World/Table"
SEAT, TOP = f"{CHAIR}/Geom/Seat", f"{TABLE}/Top"


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _synchronized(
    bindings: Bindings, stage: Usd.Stage, time_code: float = 0.0, payload_policy: PayloadPolicy = PayloadPolicy.LOAD_ALL
) -> BindingHandle:
    handle = bindings.create_binding(_scene(), payload_policy=payload_policy, name="Shot")
    assert handle.attach(stage).state is not ResultState.FATAL_FAILURE
    assert handle.synchronize(time_code).state is not ResultState.FATAL_FAILURE
    return handle


def _object(handle: BindingHandle, path: str) -> bpy.types.Object:
    [obj] = handle.highlight_targets([path])
    return obj


def _selected(handle: BindingHandle) -> set[str]:
    """The source paths of the display's objects selected in the active view layer."""
    view_layer = _scene().view_layers[0]
    return {
        picked.source_path
        for obj in bpy.data.collections["Shot"].all_objects
        if obj.select_get(view_layer=view_layer) and (picked := handle.resolve_pick(obj, obj.matrix_world)) is not None
    }


def test_setting_stores_and_mirrors(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-27, ICON-28 through api/: setting a scene's source selection stores it, selects exactly the objects of its
    # targets' expanded entities, and makes the active entry's one object active.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        chair, top = SelectionEntry(handle.binding_id, CHAIR), SelectionEntry(handle.binding_id, TOP)
        selection = PersistentSelection((chair, top), top)
        bindings.set_source_selection(_scene(), selection)
        assert bindings.source_selection(_scene()) == selection
        assert _selected(handle) == {*scene.elements[0.0]} & {SEAT, f"{CHAIR}/Geom/Back", f"{CHAIR}/Legs", TOP}
        assert _scene().view_layers[0].objects.active == _object(handle, TOP)
        bindings.set_source_selection(_scene(), PersistentSelection((chair,), chair))
        assert _selected(handle) == {SEAT, f"{CHAIR}/Geom/Back", f"{CHAIR}/Legs"}
        assert _scene().view_layers[0].objects.active is None  # Chair has three objects


def test_hidden_entries_stay_stored_and_unresolved(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-25, ICON-26 on F-UNIVERSE-MEMBERSHIP: synchronized at 0, Blinker and Shown resolve; at 5, where animated
    # visibility hides Blinker, it stays stored and is reported unresolved, and its objects aren't selected; at 0 again
    # it resolves.
    with interaction.universe_membership(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage, 0.0, PayloadPolicy.LOAD_NONE)
        blinker, shown = (
            SelectionEntry(handle.binding_id, "/World/Blinker"),
            SelectionEntry(handle.binding_id, "/World/Shown"),
        )
        selection = PersistentSelection((blinker, shown), None)
        bindings.set_source_selection(_scene(), selection)
        assert bindings.resolve_source_selection(_scene()).resolved == (blinker, shown)
        assert handle.synchronize(5.0).state is not ResultState.FATAL_FAILURE
        resolution = bindings.resolve_source_selection(_scene())
        assert (resolution.resolved, resolution.unresolved) == ((shown,), (blinker,))
        assert bindings.source_selection(_scene()) == selection
        bindings.set_source_selection(_scene(), selection)
        assert "/World/Blinker/Box" not in _selected(handle)
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        assert bindings.resolve_source_selection(_scene()).resolved == (blinker, shown)


def test_entries_without_a_live_stage_stay_stored(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-09 through api/: released, the binding's entries are unresolved and stay stored.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        selection = PersistentSelection((SelectionEntry(handle.binding_id, CHAIR),), None)
        bindings.set_source_selection(_scene(), selection)
        handle.release()
        assert bindings.resolve_source_selection(_scene()).unresolved == selection.entries
        assert bindings.source_selection(_scene()) == selection


def test_picks_change_the_selection_in_each_mode(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-30 through api/, M4's modes: picks at the component level set, extend, toggle, and subtract their targets,
    # each picked target active while selected; a pick of nothing empties the selection in set mode only.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        chair, table = SelectionEntry(handle.binding_id, CHAIR), SelectionEntry(handle.binding_id, TABLE)
        seat, top = _object(handle, SEAT), _object(handle, TOP)
        steps = [
            (seat, SelectionMode.SET, PersistentSelection((chair,), chair)),
            (top, SelectionMode.EXTEND, PersistentSelection((chair, table), table)),
            (seat, SelectionMode.TOGGLE, PersistentSelection((table,), table)),
            (seat, SelectionMode.TOGGLE, PersistentSelection((table, chair), chair)),
            (top, SelectionMode.SUBTRACT, PersistentSelection((chair,), chair)),
            (None, SelectionMode.EXTEND, PersistentSelection((chair,), chair)),
            (None, SelectionMode.SET, PersistentSelection((), None)),
        ]
        for obj, mode, expected in steps:
            world = obj.matrix_world if obj is not None else None
            bindings.select_by_pick(_scene(), obj, world, "component", mode)
            assert bindings.source_selection(_scene()) == expected, (obj, mode)


def _usd_centers(stage: Usd.Stage, paths: frozenset[str]) -> dict[str, Vector]:
    """Each element's world bounds' center from USD: its extent's center through its local-to-world transform."""
    centers = {}
    for path in paths:
        prim = stage.GetPrimAtPath(path)
        extent = UsdGeom.Boundable(prim).ComputeExtent(Usd.TimeCode(0.0))
        local = (Gf.Vec3d(extent[0]) + Gf.Vec3d(extent[1])) / 2
        world = UsdGeom.Imageable(prim).ComputeLocalToWorldTransform(Usd.TimeCode(0.0)).Transform(local)
        centers[path] = Vector(world)
    return centers


@pytest.mark.parametrize("mode", list(SelectionMode))
def test_a_box_selects_the_elements_whose_centers_are_inside(
    bindings: Bindings, tmp_path: Path, mode: SelectionMode
) -> None:
    # ICON-40 on F-KIND-HIERARCHY: starting from Chair selected, a box holding the elements whose world bounds' centers
    # lie below x = 4.25, beyond Top's and Vase's origins, selects their component-level targets in each mode.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        centers = _usd_centers(scene.stage, scene.elements[0.0])
        cut = 4.25  # Chair, Shade, and Debris inside; Table's Top and Vase, whose origins are at 4, outside
        inside = {p for p, c in centers.items() if c.x < cut}
        assert inside and inside != set(centers)
        targets = list(
            dict.fromkeys(interaction_oracle.kind_target(scene.stage, path, "component") for path in sorted(inside))
        )
        boxed = {SelectionEntry(handle.binding_id, t) for t in targets}
        chair = SelectionEntry(handle.binding_id, CHAIR)
        bindings.set_source_selection(_scene(), PersistentSelection((chair,), chair))
        bindings.select_by_box(_scene(), lambda point: point.x < cut, "component", mode)
        expected = {
            SelectionMode.SET: boxed,
            SelectionMode.EXTEND: boxed | {chair},
            SelectionMode.TOGGLE: boxed ^ {chair},
            SelectionMode.SUBTRACT: {chair} - boxed,
        }[mode]
        assert set(bindings.source_selection(_scene()).entries) == expected


def test_listeners_are_called_once_per_change(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-31's notification: a listener is called with the scene once for each change to its source selection, not
    # for setting what is stored already, and not once removed.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        calls: list[bpy.types.Scene] = []
        bindings.add_selection_listener(calls.append)
        chair = PersistentSelection((SelectionEntry(handle.binding_id, CHAIR),), None)
        bindings.set_source_selection(_scene(), chair)
        bindings.set_source_selection(_scene(), chair)
        top = _object(handle, TOP)
        bindings.select_by_pick(_scene(), top, top.matrix_world, None, SelectionMode.EXTEND)
        assert calls == [_scene(), _scene()]
        bindings.remove_selection_listener(calls.append)
        bindings.set_source_selection(_scene(), PersistentSelection((), None))
        assert len(calls) == 2


def test_a_box_skips_elements_hidden_in_the_viewport(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-40: a box identifies viewport elements only, so with Top's object hidden, a box over everything selects
    # Table, Top's component, no longer, and Vase still.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        _object(handle, TOP).hide_viewport = True
        bindings.select_by_box(_scene(), lambda _: True, "component", SelectionMode.SET)
        selected = {e.path for e in bindings.source_selection(_scene()).entries}
        assert TABLE not in selected
        assert {CHAIR, "/World/Table/Vase"} <= selected
