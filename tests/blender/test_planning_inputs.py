"""A synchronization plans under its binding's requested settings and target scene's unit scale (M6 plan, D2).

The transaction passes the planner's plan the binding's conversion and purpose settings and the target scene's unit
scale; the published generation and last attempt record them, and cache plans under the generation's. Expected
transforms and participation come from how the fixtures are built (fixtures/evaluation.py, fixtures/transaction.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest
from mathutils import Matrix

from fixtures import evaluation, transaction
from fixtures.transaction import translation
from proscenium_sync.persistence import binding_state, id_property_records
from proscenium_sync.persistence.manifests import RepresentationRole
from proscenium_sync.results import DiagnosticCode, ResultState
from proscenium_sync.runtime import ownership
from proscenium_sync.synchronization import application
from support.usd import binding_on_file

if TYPE_CHECKING:
    from pathlib import Path

    from pxr import Gf

    from proscenium_sync.bindings import BindingHandle, Bindings

MOVER = "/World/Mover"


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _objects(handle: BindingHandle) -> dict[str, bpy.types.Object]:
    """The published display's objects by the source each shows."""
    manifest = ownership.manifest(handle.binding_id)
    assert isinstance(manifest, id_property_records.LoadedRecord)
    found = {}
    for entry in manifest.record.entries.values():
        if entry.role is RepresentationRole.OBJECT:
            assert isinstance(entry.datablock, bpy.types.Object)
            found[entry.source_entity_paths[0]] = entry.datablock
    return found


def _blender(matrix: Gf.Matrix4d) -> Matrix:
    """USD's row-vector matrix as Blender's column-vector one."""
    return Matrix([[matrix[r, c] for c in range(4)] for r in range(4)]).transposed()


def _close(shown: Matrix, expected: Matrix) -> bool:
    return all(
        abs(shown[r][c] - expected[r][c]) <= 1e-4 * max(1.0, abs(expected[r][c])) for r in range(4) for c in range(4)
    )


@pytest.mark.parametrize("scale_length", evaluation.UNIT_SCALES)
@pytest.mark.parametrize("stage", ["y-up-cm", "z-up-m"])
@pytest.mark.parametrize("conversion", [False, True], ids=["conversion-off", "conversion-on"])
def test_a_synchronization_plans_under_the_binding_settings_and_scene_scale(
    bindings: Bindings, tmp_path: Path, stage: str, scale_length: float, conversion: bool
) -> None:
    # CONV-01, CONV-03, CONV-08 on F-UNITS-UP-AXIS "conversion-off" and "conversion-on": each copy's object at its
    # USD world transform, or with conversion on that under the fixture's correction for the target scene's scale.
    with evaluation.units_up_axis(tmp_path) as scene:
        _scene().unit_settings.scale_length = scale_length
        handle = binding_on_file(bindings, _scene(), scene.root_layer_paths[stage], name="Shot")
        assert handle.set_settings(coordinate_conversion=conversion).state is ResultState.SUCCESS
        assert handle.synchronize(0).state is ResultState.SUCCESS
        objects = _objects(handle)
        assert objects.keys() == scene.world_matrices_by_source.keys()
        correction = scene.correction(stage, scale_length)
        for path, world in scene.world_matrices_by_source.items():
            expected = world * correction if conversion else world
            assert _close(objects[path].matrix_world, _blender(expected)), path


def _unit_settings(scene: bpy.types.Scene) -> tuple[object, ...]:
    settings = scene.unit_settings
    return (settings.system, settings.scale_length, settings.length_unit)


@pytest.mark.parametrize(("scale_length", "length_unit"), [(1.0, "METERS"), (0.01, "CENTIMETERS")])
def test_conversion_leaves_the_scene_unit_settings(
    bindings: Bindings, tmp_path: Path, scale_length: float, length_unit: str
) -> None:
    # CONV-02 on F-UNITS-UP-AXIS "scene-settings": with conversion on, each copy's object shows its world transform
    # under the correction for the target scene's scale, and the scene's unit system, scale, and length unit are as
    # they were.
    with evaluation.units_up_axis(tmp_path) as scene:
        units = _scene().unit_settings
        units.system, units.scale_length = "METRIC", scale_length
        units.length_unit = length_unit  # ty: ignore[invalid-assignment] - the stubs list only DEFAULT
        before = _unit_settings(_scene())
        handle = binding_on_file(bindings, _scene(), scene.root_layer_paths["y-up-cm"], name="Shot")
        assert handle.set_settings(coordinate_conversion=True).state is ResultState.SUCCESS
        assert handle.synchronize(0).state is ResultState.SUCCESS
        assert _unit_settings(_scene()) == before
        objects, correction = _objects(handle), scene.correction("y-up-cm", scale_length)
        for path, world in scene.world_matrices_by_source.items():
            assert _close(objects[path].matrix_world, _blender(world * correction)), path


def test_a_destination_in_a_scene_of_another_unit_scale_is_diagnosed(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CONV-07 on F-UNITS-UP-AXIS "linked-elsewhere": the destination, also linked into a scene of another unit scale
    # (through a collection of its own) and one of the same, gets a diagnostic for the other only, naming it, the
    # destination, and both scales, which the generation records; it's found before preparation, since a failing
    # preparation reports it too.
    with evaluation.units_up_axis(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root_layer_paths["z-up-m"], name="Shot")
        destination = bpy.data.collections["Shot"]
        other, same = bpy.data.scenes.new("Other"), bpy.data.scenes.new("Same")
        other.unit_settings.scale_length = 0.01
        group = bpy.data.collections.new("Group")
        other.collection.children.link(group)
        group.children.link(destination)
        same.collection.children.link(destination)
        result = handle.synchronize(0)
        assert result.state is ResultState.COMPLETED_WITH_ISSUES
        [mismatch] = result.diagnostics
        assert mismatch.code is DiagnosticCode.UNIT_SCALE_MISMATCH
        assert all(text in mismatch.message for text in ("'Shot'", "'Other'", "0.01", "'Scene'", " 1,"))
        generation = binding_state.read_generation(destination)
        assert isinstance(generation, id_property_records.LoadedRecord)
        assert generation.record.diagnostics == (mismatch,)

        def failing(*_args: object) -> None:
            raise RuntimeError("injected preparation failure")

        monkeypatch.setattr(application, "prepare", failing)
        codes = [d.code for d in handle.synchronize(0).diagnostics]
        assert codes == [DiagnosticCode.UNIT_SCALE_MISMATCH, DiagnosticCode.PREPARATION_FAILED]


def test_a_synchronization_shows_the_binding_purposes(bindings: Bindings, tmp_path: Path) -> None:
    # VIS-02, VIS-03 on F-VISIBILITY-PURPOSE "purpose-settings": the binding's purposes, not the defaults, decide each
    # destination's copies; a copy whose purpose neither includes isn't drawn.
    viewport, render = ("default", "render"), ("proxy",)
    with evaluation.visibility_purpose(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root_layer_path, name="Shot")
        result = handle.set_settings(viewport_purposes=viewport, render_purposes=render)
        assert result.state is ResultState.SUCCESS
        assert handle.synchronize(0).state is ResultState.SUCCESS
        hidden = {path: (obj.hide_viewport, obj.hide_render) for path, obj in _objects(handle).items()}
        assert hidden == {
            path: (not scene.displays(path, 0.0, viewport), not scene.displays(path, 0.0, render))
            for path, purpose in scene.purpose.items()
            if purpose in {*viewport, *render}
        }


def test_the_records_hold_what_the_synchronization_planned_under(bindings: Bindings, tmp_path: Path) -> None:
    # The generation records the settings and unit scale it was planned with, and the last attempt the settings it
    # requested (STATE-01, STATE-03); a later set_settings changes neither.
    with transaction.cached_time_codes(tmp_path) as scene:
        _scene().unit_settings.scale_length = 0.01
        handle = bindings.create_binding(_scene(), name="Shot")
        assert handle.attach(scene.caller).state is ResultState.SUCCESS
        handle.set_settings(coordinate_conversion=True, viewport_purposes=["default"], render_purposes=["render"])
        requested = handle.requested_settings()
        assert handle.synchronize(scene.synchronized).state is ResultState.SUCCESS
        handle.set_settings(coordinate_conversion=False)
        destination = bpy.data.collections["Shot"]
        generation = binding_state.read_generation(destination)
        attempt = binding_state.read_last_attempt(destination)
        assert isinstance(generation, id_property_records.LoadedRecord) and isinstance(
            attempt, id_property_records.LoadedRecord
        )
        assert (generation.record.applied_settings, generation.record.unit_scale) == (requested, pytest.approx(0.01))
        assert attempt.record.attempted_settings == requested


def _cached(bindings: Bindings, scene: transaction.CachedTimeCodesScene) -> BindingHandle:
    handle = bindings.create_binding(_scene(), name="Shot")
    assert handle.attach(scene.caller).state is ResultState.SUCCESS
    assert handle.synchronize(scene.synchronized).state is ResultState.SUCCESS
    return handle


def test_cache_plans_under_the_generation_settings(bindings: Bindings, tmp_path: Path) -> None:
    # pipeline.md's "under the generation's settings": conversion requested after the synchronization, on a stage in
    # centimeters, leaves the cached time codes unconverted, as the display is.
    with transaction.cached_time_codes(tmp_path) as scene:
        handle = _cached(bindings, scene)
        assert handle.set_settings(coordinate_conversion=True).state is ResultState.SUCCESS
        assert handle.cache(scene.cached).state is ResultState.SUCCESS
        mover = _objects(handle)[MOVER]
        for time_code in (scene.synchronized, *scene.cached):
            _scene().frame_set(int(time_code), subframe=time_code % 1)
            assert tuple(mover.matrix_world.translation[:]) == pytest.approx(translation(MOVER, time_code))


def test_after_the_unit_scale_changes_cache_needs_a_synchronization(bindings: Bindings, tmp_path: Path) -> None:
    # CACHE-12 on F-CACHED-TIME-CODES "changed-unit-scale": cache fails saying the binding needs synchronizing and
    # caches nothing, its cached time codes included; with the scale set back, or once synchronized again, it caches.
    with transaction.cached_time_codes(tmp_path) as scene:
        handle = _cached(bindings, scene)
        first, *rest = scene.cached
        assert handle.cache([first]).state is ResultState.SUCCESS
        _scene().unit_settings.scale_length = 0.01
        destination = bpy.data.collections["Shot"]
        before = binding_state.read_generation(destination)
        actions = set(bpy.data.actions)
        for time_codes in (rest, [first]):
            result = handle.cache(time_codes)
            assert [d.code for d in result.diagnostics] == [DiagnosticCode.NEEDS_SYNCHRONIZATION]
            assert binding_state.read_generation(destination) == before
            assert set(bpy.data.actions) == actions
        _scene().unit_settings.scale_length = 1.0
        assert handle.cache(rest[:1]).state is ResultState.SUCCESS
        _scene().unit_settings.scale_length = 0.01
        assert handle.synchronize(scene.synchronized).state is ResultState.SUCCESS
        assert handle.cache(rest).state is ResultState.SUCCESS
