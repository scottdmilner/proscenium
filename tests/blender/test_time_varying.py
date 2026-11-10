"""Time-varying values at each sampled time code, synchronized and cached (M6 plan, E2; XFORM-06, AFIX-06).

At each of a time-varying fixture's sampled time codes (support/time_codes.py), the plan a synchronization builds and
the one a cache call builds hold each drawn copy's world transform and participation as the fixture gives them there:
F-TRANSFORMS' Animated's translate under both payload policies, and F-VISIBILITY-PURPOSE's Blinking's visibility.
The plans are read as the transaction gets them, through a spy on synchronization.evaluation.evaluate_display_plans; a
synchronization's published objects show its plan, and a cache call's keys its transforms. Cached visibility is
M7's, so a cache call's participation is checked on its plans alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy
import pytest
from mathutils import Matrix
from pxr import Gf, Usd

from fixtures import evaluation
from proscenium.binding.persistence import records
from proscenium.binding.persistence.manifests import RepresentationRole
from proscenium.binding.results import ResultState
from proscenium.binding.runtime import ownership
from proscenium.binding.source_access.stages import PayloadPolicy
from proscenium.synchronization import evaluation as planning
from support import time_codes
from support.usd import binding_on_file

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from proscenium.api.bindings import BindingHandle, Bindings
    from proscenium.core import _core


@dataclass(frozen=True)
class Expected:
    """What a fixture is built to display at each time code."""

    root: Path
    sampled: time_codes.SampledTimeCodes
    world: Callable[[str, float | None], Gf.Matrix4d] | None  # drawn mesh, time code -> world transform, or unchecked
    shown: Callable[[str, float | None], tuple[bool, bool]]  # -> whether it displays in the viewport and render
    drawn: frozenset[str]


@dataclass(frozen=True)
class Shown:
    """A drawn copy as a plan gives it."""

    world: Gf.Matrix4d  # USD's row-vector convention
    viewport: bool
    render: bool


@pytest.fixture
def plans(monkeypatch: pytest.MonkeyPatch) -> list[_core.Plan]:
    """Every plan the transaction and cache calls get from evaluation.evaluate_display_plans, in order."""
    got: list[_core.Plan] = []
    original = planning.evaluate_display_plans

    def spy(*args: object) -> object:
        planned = original(*args)  # ty: ignore[invalid-argument-type] - passed through as given
        assert isinstance(planned, list), planned  # no fatal diagnostic
        got.extend(planned)
        return planned

    monkeypatch.setattr(planning, "evaluate_display_plans", spy)
    return got


def _transforms(tmp_path: Path, policy: PayloadPolicy) -> Generator[Expected]:
    with evaluation.transforms(tmp_path) as scene:
        yield Expected(
            scene.root,
            time_codes.sampled("F-TRANSFORMS", scene.variation),
            scene.world_at,
            lambda _path, _time_code: (True, True),  # every mesh is of the default purpose and visible
            scene.drawn(policy),
        )


def _visibility(tmp_path: Path, _policy: PayloadPolicy) -> Generator[Expected]:
    with evaluation.visibility_purpose(tmp_path) as scene:
        yield Expected(
            scene.root,
            time_codes.sampled("F-VISIBILITY-PURPOSE", scene.variation),
            None,  # its transforms don't vary, and are F-TRANSFORMS' to check
            lambda path, t: (
                scene.displays(path, t, evaluation.VIEWPORT_PURPOSES),
                scene.displays(path, t, evaluation.RENDER_PURPOSES),
            ),
            frozenset(p for p, purpose in scene.purpose.items() if purpose != "guide"),  # never explicitly visible
        )


CASES = {
    "transforms-load-all": (_transforms, PayloadPolicy.LOAD_ALL),
    "transforms-load-none": (_transforms, PayloadPolicy.LOAD_NONE),  # a payloaded fixture under both (AFIX-06)
    "visibility": (_visibility, PayloadPolicy.LOAD_ALL),
}


def _value(time_code: Usd.TimeCode) -> float | None:
    return None if time_code.IsDefault() else time_code.GetValue()


def _shown(plan: _core.Plan) -> dict[str, Shown]:
    """Each drawn copy by its source."""
    worlds = memoryview(plan.copy_worlds).tolist()
    viewport, render = memoryview(plan.copy_viewport).tolist(), memoryview(plan.copy_render).tolist()
    sources = {c.object_resource_index: c.source for c in plan.correspondence}
    return {
        sources[obj]: Shown(Gf.Matrix4d(*worlds[16 * copy : 16 * copy + 16]), bool(viewport[copy]), bool(render[copy]))
        for copy, obj in enumerate(memoryview(plan.copy_objects).tolist())
    }


def _close(shown: Gf.Matrix4d, expected: Gf.Matrix4d) -> bool:
    """Within the 32-bit floats' precision the plan's matrices hold."""
    return all(
        abs(shown[r, c] - expected[r, c]) <= 1e-4 * max(1.0, abs(expected[r, c])) for r in range(4) for c in range(4)
    )


def _check(plan: _core.Plan, expected: Expected) -> None:
    time_code = _value(plan.time_code)
    shown = _shown(plan)
    assert shown.keys() == expected.drawn, time_code
    for path, copy in shown.items():
        if expected.world is not None:
            assert _close(copy.world, expected.world(path, time_code)), (path, time_code)
        assert (copy.viewport, copy.render) == expected.shown(path, time_code), (path, time_code)


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


def _usd(matrix: Matrix) -> Gf.Matrix4d:
    return Gf.Matrix4d(*(matrix[c][r] for r in range(4) for c in range(4)))


def _composed(obj: bpy.types.Object) -> Matrix:
    """Obj's world transform as Blender composes it from what each object stores, a shear parent's shear included."""
    return obj.matrix_basis if obj.parent is None else obj.parent.matrix_world @ obj.matrix_basis


def _frame_set(time_code: float) -> None:
    frame = int(time_code // 1)
    bpy.data.scenes["Scene"].frame_set(frame, subframe=time_code - frame)


@pytest.mark.parametrize("case", CASES)
def test_each_sampled_time_code_synchronized(
    bindings: Bindings, tmp_path: Path, plans: list[_core.Plan], case: str
) -> None:
    # XFORM-06 on F-TRANSFORMS "time-codes" and F-VISIBILITY-PURPOSE "time-varying": each synchronization's plan holds
    # the fixture's world transforms and participation at its time code, and its published objects show them.
    build, policy = CASES[case]
    for expected in build(tmp_path, policy):
        handle = binding_on_file(bindings, bpy.data.scenes["Scene"], expected.root, payload_policy=policy, name="Shot")
        for time_code in expected.sampled.time_codes:
            given = Usd.TimeCode.Default() if time_code is None else Usd.TimeCode(time_code)
            assert handle.synchronize(given).state is ResultState.SUCCESS, time_code
            [plan] = plans
            plans.clear()
            assert _value(plan.time_code) == time_code
            _check(plan, expected)
            for path, obj in _objects(handle).items():
                if expected.world is not None:
                    assert _close(_usd(_composed(obj)), expected.world(path, time_code)), (path, time_code)
                assert (not obj.hide_viewport, not obj.hide_render) == expected.shown(path, time_code), path


@pytest.mark.parametrize("case", CASES)
def test_each_sampled_time_code_cached(bindings: Bindings, tmp_path: Path, plans: list[_core.Plan], case: str) -> None:
    # XFORM-06 on F-TRANSFORMS "cached-time-codes" and F-VISIBILITY-PURPOSE "time-varying": synchronized at the
    # start, one cache call's plans, one per other sampled time code but the default, which isn't one to cache, hold
    # the fixture's values at each, and each object shows its world transform there.
    build, policy = CASES[case]
    for expected in build(tmp_path, policy):
        handle = binding_on_file(bindings, bpy.data.scenes["Scene"], expected.root, payload_policy=policy, name="Shot")
        synchronized = expected.sampled.start  # a generation at the default time code has nothing to cache
        assert handle.synchronize(synchronized).state is ResultState.SUCCESS
        plans.clear()
        cached = [t for t in expected.sampled.time_codes if t is not None and t != synchronized]
        assert handle.cache(cached).state is ResultState.SUCCESS
        assert [_value(p.time_code) for p in plans] == cached
        for plan in plans:
            _check(plan, expected)
        if (world := expected.world) is None:
            return
        objects = _objects(handle)
        for time_code in [synchronized, *cached]:
            _frame_set(time_code)
            for path, obj in objects.items():
                assert _close(_usd(_composed(obj)), world(path, time_code)), (path, time_code)
