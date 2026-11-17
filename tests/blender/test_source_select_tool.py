"""The Source Select tool's session, headless (M7 plan, F5; from M4's test_select_tool_session).

The tool's window parts, the keymap, the drawn box, and a ray from the cursor, are tried by hand ("Interaction
feasibility evidence"). Here its picks come from rays the test casts at each element's world bounds' center, computed
with USD's own APIs, its box from an orthographic projection onto the XY plane, and its sidebar draws into a layout
that records what it was given. Expected targets come from support/interaction_oracle.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
from mathutils import Vector
from pxr import Gf, Usd, UsdGeom

from fixtures import interaction
from proscenium.interface import interface_registration, source_select_tool
from proscenium_sync.bindings import PersistentSelection, SelectionEntry
from proscenium_sync.results import ResultState
from proscenium_sync.source_access.binding_settings import PayloadPolicy
from support import interaction_oracle, undo
from support.recording_layout import RecordingLayout

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium_sync.bindings import BindingHandle, Bindings

DOWN = Vector((0.0, 0.0, -1.0))


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _synchronized(
    bindings: Bindings, stage: Usd.Stage, policy: PayloadPolicy = PayloadPolicy.LOAD_ALL
) -> BindingHandle:
    handle = bindings.create_binding(_scene(), payload_policy=policy, name="Shot")
    assert handle.attach(stage).state is not ResultState.FATAL_FAILURE
    assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
    return handle


def _set_level(level: str) -> None:
    setattr(_scene(), source_select_tool.LEVEL_PROPERTY, level)


def _center(stage: Usd.Stage, path: str) -> Vector:
    """The world bounds' center of the prim at path, from USD: its extent's center through its world transform."""
    prim = stage.GetPrimAtPath(path)
    extent = UsdGeom.Boundable(prim).ComputeExtent(Usd.TimeCode(0.0))
    local = (Gf.Vec3d(extent[0]) + Gf.Vec3d(extent[1])) / 2
    return Vector(UsdGeom.Imageable(prim).ComputeLocalToWorldTransform(Usd.TimeCode(0.0)).Transform(local))


def _cast_down(at: Vector, near_marker: Any = lambda _: False) -> tuple[bpy.types.Object, Any] | None:
    view_layer = _scene().view_layers[0]
    view_layer.update()  # world matrices are current at an update, as a viewport has them before a click
    origin = at + Vector((0.0, 0.0, 100.0))
    return source_select_tool.bounds_ray_cast(source_select_tool.pickable(view_layer), origin, DOWN, near_marker)


def test_a_click_picks_what_its_ray_hits(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-36 through the tool: a ray down at each element's world bounds' center hits an object showing an element
    # there, which resolves to an entity at that center; picked at the component level it selects that entity's target.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        _set_level("component")
        for path in sorted(scene.elements[0.0]):
            center = _center(scene.stage, path)
            hit = _cast_down(center)
            assert hit is not None, path
            obj, matrix = hit
            assert matrix == obj.matrix_world
            picked = handle.resolve_pick(obj, matrix)
            assert picked is not None and (_center(scene.stage, picked.source_path) - center).length < 1e-6, path
            source_select_tool.pick(_scene(), hit, "SET")
            target = interaction_oracle.kind_target(scene.stage, picked.floor, "component")
            assert bindings.source_selection(_scene()) == PersistentSelection(
                (SelectionEntry(handle.binding_id, target),), SelectionEntry(handle.binding_id, target)
            ), path


def test_modifiers_toggle_and_remove_and_nothing_clears(bindings: Bindings, tmp_path: Path) -> None:
    # The tool's keymap modes: shift toggles a target, ctrl removes it, and a click on nothing clears the selection.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        shade, top = (_cast_down(_center(scene.stage, p)) for p in ("/World/Props/Lamp/Shade", "/World/Table/Top"))
        source_select_tool.pick(_scene(), shade, "SET")
        source_select_tool.pick(_scene(), top, "TOGGLE")
        assert len(bindings.source_selection(_scene()).entries) == 2
        source_select_tool.pick(_scene(), shade, "TOGGLE")
        source_select_tool.pick(_scene(), top, "SUBTRACT")
        assert not bindings.source_selection(_scene()).entries
        source_select_tool.pick(_scene(), shade, "SET")
        assert _cast_down(Vector((50.0, 50.0, 0.0))) is None
        source_select_tool.pick(_scene(), None, "SET")
        assert not bindings.source_selection(_scene()).entries
        del handle


def test_a_marker_is_picked_near_its_origin(bindings: Bindings, tmp_path: Path) -> None:
    # An empty marker has no bounds a ray can enter, so a click picks it near its origin, as the tool's few pixels are
    # in a view: cast at the marker alone, a ray down through its origin hits it, at its world matrix, and one the
    # marker test says passes far from it misses.
    with interaction.universe_membership(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage, PayloadPolicy.LOAD_NONE)
        [marker] = handle.highlight_targets(["/World/Marker"])
        _scene().view_layers[0].update()
        at = marker.matrix_world.translation.copy()
        origin = at + Vector((0.0, 0.0, 100.0))
        hit = source_select_tool.bounds_ray_cast([marker], origin, DOWN, lambda _: True)
        assert hit is not None and hit[0] == marker and hit[1] == marker.matrix_world
        assert source_select_tool.bounds_ray_cast([marker], origin, DOWN, lambda _: False) is None


def test_a_box_selects_by_projected_centers(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-40 through the tool: a box over x < 3 and y < 1 in a top view selects the component-level targets of the
    # elements whose world bounds' centers project inside it.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        _set_level("component")
        inside = sorted(p for p in scene.elements[0.0] if (c := _center(scene.stage, p)).x < 3 and -1 < c.y < 1)
        assert inside
        source_select_tool.box(_scene(), lambda p: Vector((p.x, p.y)), ((-1.0, -1.0), (3.0, 1.0)), "SET")
        expected = {interaction_oracle.kind_target(scene.stage, p, "component") for p in inside}
        assert {e.path for e in bindings.source_selection(_scene()).entries} == expected
        del handle


def test_the_level_property_is_the_selection_level(bindings: Bindings) -> None:
    del bindings
    _set_level(source_select_tool.PRIM_LEVEL)
    assert source_select_tool.selection_level(_scene()) is None
    _set_level("assembly")
    assert source_select_tool.selection_level(_scene()) == "assembly"
    assert {item[0] for item in source_select_tool.levels()} == {"PRIM", *interaction_oracle.levels()[1:]}


def test_selection_operators_are_undo_steps() -> None:
    # The tool's operators declare UNDO, as Blender's selection operators do; the API pushes no step for a selection.
    for operator in (source_select_tool.PROSCENIUM_OT_source_pick, source_select_tool.PROSCENIUM_OT_source_box):
        assert "UNDO" in operator.bl_options


def test_in_background_mode_selectability_is_left_alone(bindings: Bindings, tmp_path: Path) -> None:
    # In background mode no tool is used, though the file holds a window, so following the tool changes nothing; a
    # binding created while the scene's managed content is unselectable gets an unselectable destination.
    with interaction.kind_hierarchy(tmp_path) as scene:
        _synchronized(bindings, scene.stage)
        source_select_tool.update_selectability()
        assert bindings.managed_selectable(_scene())
        bindings.set_managed_selectable(_scene(), False)
        other = bindings.create_binding(_scene(), name="Other")
        assert bpy.data.collections["Other"].hide_select
        del other


def test_the_sidebar_lists_the_scene_selection(bindings: Bindings, tmp_path: Path) -> None:
    # The sidebar's panel draws the level and each target, the active one marked and an unresolved one dimmed.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        chair, gone = (
            SelectionEntry(handle.binding_id, "/World/Props/Chair"),
            SelectionEntry(handle.binding_id, "/Nowhere"),
        )
        bindings.set_source_selection(_scene(), PersistentSelection((chair, gone), chair))
        layout = RecordingLayout()
        source_select_tool.draw_source_selection(layout, _scene())
        assert layout.props == [source_select_tool.LEVEL_PROPERTY]
        assert layout.labels == [("/World/Props/Chair", "RADIOBUT_ON", True), ("/Nowhere", "DOT", False)]
        bindings.set_source_selection(_scene(), PersistentSelection((), None))
        layout = RecordingLayout()
        source_select_tool.draw_source_selection(layout, _scene())
        assert layout.labels == [("Nothing selected", "NONE", True)]


def test_the_tools_classes_are_registered(bindings: Bindings) -> None:
    del bindings  # the extension registered
    for cls in source_select_tool.CLASSES:
        assert cls.is_registered, cls.__name__


def test_a_ray_hits_the_nearest_object_it_shows(bindings: Bindings, tmp_path: Path) -> None:
    # A ray along x at y = 0.5 passes through Chair's parts, then Shade, then Table's Top: it hits a part of Chair, the
    # nearest; with Chair's objects hidden in the viewport, which a click can't hit, it hits Shade.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        view_layer = _scene().view_layers[0]
        chair = handle.highlight_targets(["/World/Props/Chair"])
        origin, along = Vector((-10.0, 0.5, 0.0)), Vector((1.0, 0.0, 0.0))

        def hit_path() -> str | None:
            view_layer.update()
            objects = source_select_tool.pickable(view_layer)
            hit = source_select_tool.bounds_ray_cast(objects, origin, along, lambda _: False)
            picked = None if hit is None else handle.resolve_pick(*hit)
            return None if picked is None else picked.source_path

        assert hit_path() in {"/World/Props/Chair/Geom/Seat", "/World/Props/Chair/Geom/Back", "/World/Props/Chair/Legs"}
        for obj in chair:
            obj.hide_viewport = True
        assert hit_path() == "/World/Props/Lamp/Shade"


def test_undo_past_the_tools_activation_keeps_content_selectable(bindings: Bindings, tmp_path: Path) -> None:
    # Activating Source Select is no undo step, so undoing past a pick made since restores the destination's
    # hide_select from before the activation: managed content unselectable, and nothing mirrored. After an undo or a
    # redo the UI recomputes selectability from the active tool (its handlers, registered here, call
    # update_selectability, which background mode skips); applied for the scene showing the tool, content is selectable
    # again and the restored selection mirrored. Views are looked up again after each undo, which rebuilds them.
    undo.require_global_undo()
    assert interface_registration._undone_or_redone in bpy.app.handlers.undo_post  # noqa: SLF001
    assert interface_registration._undone_or_redone in bpy.app.handlers.redo_post  # noqa: SLF001
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        bindings.set_managed_selectable(_scene(), False)  # another tool active
        undo.push("before the tool's activation")
        bindings.set_managed_selectable(_scene(), True)  # Source Select activated: no undo step
        shade = _cast_down(_center(scene.stage, "/World/Props/Lamp/Shade"))
        source_select_tool.pick(_scene(), shade, "SET")
        undo.push("Source Pick")
        top = _cast_down(_center(scene.stage, "/World/Table/Top"))
        source_select_tool.pick(_scene(), top, "SET")
        undo.push("Source Pick")
        undo.undo(2)
        assert bpy.data.collections["Shot"].hide_select  # the undo step's selectability
        undo.redo()
        assert not bpy.data.collections["Shot"].hide_select
        bpy.data.collections["Shot"].hide_select = True  # as an undo step from before the activation restores it
        source_select_tool.apply_selectability({_scene()})
        assert bindings.managed_selectable(_scene())
        view_layer = _scene().view_layers[0]
        [shown] = handle.highlight_targets(["/World/Props/Lamp/Shade"])
        assert shown.select_get(view_layer=view_layer)
        source_select_tool.apply_selectability(set())
        assert not bindings.managed_selectable(_scene())
