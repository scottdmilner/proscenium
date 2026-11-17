"""The standard end-to-end checks M7 runs on M6's plans (testing/acceptance.md#standard-end-to-end-checks).

Each case synchronizes a fixture through the API at each time code it samples, under its payload policy and settings,
and checks that the synchronization isn't fatal (ASTD-01), that each model's display bounds match USD's under the
Bounds Comparison Contract (ASTD-02, support/bounds_check.py, with the plan read through a spy on
evaluation.evaluate_display_plans), and records the display's unique mesh-data count as a test property, asserting no
bound on it (ASTD-03). Each case is also saved and reopened with its source moved away, its display then compared
with what it was, and, with the source back and its stage attached again, its interaction answers compared without
synchronizing (ASTD-04). The fixtures: the bespoke evaluation ones, the interaction ones that have models,
F-NESTED-STRESS for transforms objects can't hold inside nested instances, and the production-like CI fixture under
each policy.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import bpy
import pytest
from pxr import Usd

from fixtures import appearance, evaluation, interaction, production_like
from proscenium_sync import synchronization
from proscenium_sync.api.bindings import BindingHandle
from proscenium_sync.results import ResultState
from proscenium_sync.source_access.binding_settings import PayloadPolicy
from proscenium_sync.synchronization import evaluation as planning
from support import bounds_check, time_codes
from support.blend import save_and_reopen
from support.displayed_copies import displayed_copies, unique_mesh_data_count
from support.interaction_answers import answers
from support.usd import binding_on_file, open_stage_without_cache

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from contextlib import AbstractContextManager
    from pathlib import Path

    from proscenium_sync import core
    from proscenium_sync.api.bindings import Bindings


@contextmanager
def _production_like(dest: Path) -> Iterator[Path]:
    yield production_like.generate(dest)


@dataclass(frozen=True)
class EndToEndCase:
    open_scene: Callable[[Path], AbstractContextManager[Any]]  # a fixture's generator
    root_layer_path: Callable[[Any], Path]
    sampled_time_codes: Callable[[Any], tuple[float | None, ...]]  # None: the default time code
    payload_policy: PayloadPolicy = PayloadPolicy.LOAD_ALL
    coordinate_conversion: bool = False
    unit_scale: float = 1.0  # the target scene's


def _sampled(fixture_id: str) -> Callable[[Any], tuple[float | None, ...]]:
    return lambda scene: time_codes.sampled(fixture_id, scene.variation).time_codes


def _at_zero(_scene: object) -> tuple[float | None, ...]:
    return (0.0,)


def _root(scene: Any) -> Path:
    return scene.root_layer_path


CASES = {
    **{
        f"transforms-{policy.value}": EndToEndCase(
            evaluation.transforms, _root, _sampled("F-TRANSFORMS"), payload_policy=policy
        )
        for policy in PayloadPolicy
    },
    **{
        f"units-{stage}-converted": EndToEndCase(
            evaluation.units_up_axis,
            lambda scene, stage=stage: scene.root_layer_paths[stage],
            _at_zero,
            coordinate_conversion=True,
            unit_scale=0.01,
        )
        for stage in ("y-up-cm", "z-up-m")
    },
    "visibility-purpose": EndToEndCase(evaluation.visibility_purpose, _root, _sampled("F-VISIBILITY-PURPOSE")),
    "unsupported-content": EndToEndCase(evaluation.unsupported_content, _root, _at_zero),
    "point-instancers": EndToEndCase(evaluation.point_instancers, _root, _at_zero),
    "kind-hierarchy": EndToEndCase(interaction.kind_hierarchy, _root, lambda scene: scene.times),
    "nested-selection": EndToEndCase(interaction.nested_selection, _root, lambda scene: scene.times),
    "nested-stress": EndToEndCase(appearance.nested_stress, _root, _at_zero),
    **{
        f"production-like-{policy.value}": EndToEndCase(
            _production_like, lambda root: root, _at_zero, payload_policy=policy
        )
        for policy in PayloadPolicy
    },
}


@pytest.fixture
def plans(monkeypatch: pytest.MonkeyPatch) -> list[core.Plan]:
    """Every plan the transaction gets from evaluation.evaluate_display_plans, in order."""
    got: list[core.Plan] = []
    original = planning.evaluate_display_plans

    def spy(*args: object, **kwargs: object) -> object:
        planned = original(*args, **kwargs)  # ty: ignore[invalid-argument-type] - passed through as given
        if planned is not None:
            got.extend(planned)
        return planned

    monkeypatch.setattr(planning, "evaluate_display_plans", spy)
    return got


@pytest.mark.parametrize("name", list(CASES))
def test_the_standard_end_to_end_checks(
    name: str,
    bindings: Bindings,
    tmp_path: Path,
    plans: list[core.Plan],
    record_property: Callable[[str, object], None],
) -> None:
    case = CASES[name]
    target = bpy.data.scenes["Scene"]
    target.unit_settings.scale_length = case.unit_scale
    with case.open_scene(tmp_path) as scene:
        root = case.root_layer_path(scene)
        handle = binding_on_file(bindings, target, root, payload_policy=case.payload_policy, name="Shot")
        assert handle.set_settings(coordinate_conversion=case.coordinate_conversion).state is ResultState.SUCCESS
        stage = open_stage_without_cache(root, case.payload_policy.load_set)  # USD's side, under the same policy
        correction = bounds_check.conversion_correction(stage, case.coordinate_conversion, case.unit_scale)
        unique_meshes = {}
        for time_code in case.sampled_time_codes(scene):
            usd_time = Usd.TimeCode.Default() if time_code is None else Usd.TimeCode(time_code)
            result = handle.synchronize(usd_time)
            assert result.state is not ResultState.FATAL_FAILURE, (time_code, result.diagnostics)  # ASTD-01
            planned = bounds_check.planned_copies(plans[-1])
            problems = bounds_check.model_bounds_mismatches(
                stage, usd_time, planned, displayed_copies(handle.binding_id), correction
            )
            assert problems == [], time_code  # ASTD-02
            unique_meshes[str(time_code)] = unique_mesh_data_count(handle.binding_id)
        record_property("unique mesh data by time code", unique_meshes)  # ASTD-03, recorded only


def _rounded(matrix: Any) -> list[list[float]]:
    return [[round(v, 6) for v in row] for row in matrix]


def _display(destination: bpy.types.Collection) -> dict[str, Any]:
    """The destination's objects, each one's stored transform, parent, hide flags, and mesh, by name.

    The stored transform, not matrix_world, which the depsgraph leaves stale for an object hidden in the viewport.
    """
    content = {}
    for obj in destination.objects:
        mesh = obj.data if isinstance(obj.data, bpy.types.Mesh) else None
        content[obj.name] = {
            "basis": _rounded(obj.matrix_basis),
            "parent": obj.parent and (obj.parent.name, _rounded(obj.matrix_parent_inverse)),
            "hidden": (obj.hide_viewport, obj.hide_render),
            "vertices": mesh and [[round(v, 6) for v in vertex.co] for vertex in mesh.vertices],
            "faces": mesh and [list(p.vertices) for p in mesh.polygons],
        }
    return content


@pytest.mark.parametrize("name", list(CASES))
def test_save_and_reopen_keeps_display_and_correspondence(
    name: str, bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ASTD-04: synchronized at its first sampled time code, saved, and reopened with its source moved away, each case
    # shows the same objects, transforms, hide flags, and meshes; with the source back and its stage attached again, its
    # interaction answers are those before saving, and nothing synchronizes or caches.
    case = CASES[name]
    target = bpy.data.scenes["Scene"]
    target.unit_settings.scale_length = case.unit_scale
    source, moved = tmp_path / "source", tmp_path / "moved"
    with case.open_scene(source) as scene:
        root = case.root_layer_path(scene)
        handle = binding_on_file(bindings, target, root, payload_policy=case.payload_policy, name="Shot")
        assert handle.set_settings(coordinate_conversion=case.coordinate_conversion).state is ResultState.SUCCESS
        [first, *_] = case.sampled_time_codes(scene)
        assert (
            handle.synchronize(Usd.TimeCode.Default() if first is None else first).state
            is not ResultState.FATAL_FAILURE
        )
        live = handle.live_stage()
        assert live is not None
        display = _display(bpy.data.collections["Shot"])
        before = answers(handle, live)
        source.rename(moved)
        save_and_reopen(tmp_path / "reopened.blend")
        assert _display(bpy.data.collections["Shot"]) == display
        moved.rename(source)

        def forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("synchronized or cached")

        with monkeypatch.context() as patched:
            patched.setattr(synchronization, "synchronize", forbidden)
            patched.setattr(synchronization, "cache", forbidden)
            restored = BindingHandle(handle.binding_id)
            assert restored.attach(live).state is not ResultState.FATAL_FAILURE
            assert answers(restored, live) == before
