"""A synchronization plans under its binding's requested settings and target scene's unit scale (M6 plan, D2).

The transaction passes the core's plan the binding's conversion and purpose settings and the target scene's unit
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
from proscenium.binding.persistence import binding_state, records
from proscenium.binding.persistence.manifests import RepresentationRole
from proscenium.binding.results import DiagnosticCode, ResultState
from proscenium.binding.runtime import ownership
from support.usd import binding_on_file

if TYPE_CHECKING:
    from pathlib import Path

    from pxr import Gf

    from proscenium.api.bindings import BindingHandle, Bindings

MOVER = "/World/Mover"


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _objects(handle: BindingHandle) -> dict[str, bpy.types.Object]:
    """The published display's objects by the source each shows."""
    manifest = ownership.manifest(handle.binding_id)
    assert isinstance(manifest, records.LoadedRecord)
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
        handle = binding_on_file(bindings, _scene(), scene.roots[stage], name="Shot")
        assert handle.set_settings(coordinate_conversion=conversion).state is ResultState.SUCCESS
        assert handle.synchronize(0).state is ResultState.SUCCESS
        objects = _objects(handle)
        assert objects.keys() == scene.world.keys()
        correction = scene.correction(stage, scale_length)
        for path, world in scene.world.items():
            expected = world * correction if conversion else world
            assert _close(objects[path].matrix_world, _blender(expected)), path


def test_a_synchronization_shows_the_binding_purposes(bindings: Bindings, tmp_path: Path) -> None:
    # VIS-02, VIS-03 on F-VISIBILITY-PURPOSE "purpose-settings": the binding's purposes, not the defaults, decide each
    # destination's copies; a copy whose purpose neither includes isn't drawn.
    viewport, render = ("default", "render"), ("proxy",)
    with evaluation.visibility_purpose(tmp_path) as scene:
        handle = binding_on_file(bindings, _scene(), scene.root, name="Shot")
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
        assert isinstance(generation, records.LoadedRecord) and isinstance(attempt, records.LoadedRecord)
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
