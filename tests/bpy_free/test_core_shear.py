"""World transforms Blender objects can't hold, through the plan (M6 plan, C4).

A Blender object holds only location, rotation, and scale, so a sheared copy's world transform splits into its object's
basis and a shear parent's world transform, each holding only those, whose product is the world transform (XFORM-03),
as the bridge's apply.py splits it. A projective matrix places its mesh by its affine part (XFORM-05; C6 adds the
diagnostic). Expected values come from the fixtures' construction.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest
from pxr import Gf

from fixtures import appearance, evaluation

from .plan_checks import Copy, assert_world, copies, plan_at

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def transforms(tmp_path: Path) -> Iterator[evaluation.TransformsScene]:
    with evaluation.transforms(tmp_path) as scene:
        yield scene


@pytest.fixture
def stress(tmp_path: Path) -> Iterator[appearance.StressScene]:
    with appearance.nested_stress(tmp_path) as scene:
        yield scene


def _holds_location_rotation_scale(matrix: Gf.Matrix4d) -> bool:
    """Whether the affine matrix's axes, USD's rows, are orthogonal, so it is a location, rotation, and scale."""
    assert matrix.GetColumn(3) == Gf.Vec4d(0, 0, 0, 1)
    axes = [Gf.Vec3d(*(matrix[i][j] for j in range(3))) for i in range(3)]
    return all(
        abs(axes[i] * axes[j]) <= 1e-5 * axes[i].GetLength() * axes[j].GetLength() for i, j in ((0, 1), (0, 2), (1, 2))
    )


def _assert_splits(path: str, copy: Copy, world: Gf.Matrix4d) -> None:
    assert copy.shear is not None, path
    parent, basis = copy.shear
    assert_world(dataclasses.replace(copy, world=basis * parent), world)  # the object below its parent
    assert _holds_location_rotation_scale(parent), path
    assert _holds_location_rotation_scale(basis), path
    assert basis.ExtractTranslation() == Gf.Vec3d(0), path


@pytest.mark.parametrize("fixture", ["transforms", "stress"])
def test_exactly_the_sheared_copies_get_a_shear_parent(fixture: str, request: pytest.FixtureRequest) -> None:
    scene = request.getfixturevalue(fixture)
    plan = plan_at(scene.stage, 0.0)
    shown = copies(plan)
    assert {path for path, copy in shown.items() if copy.shear is not None} == scene.sheared & shown.keys()
    for path, copy in shown.items():
        if path in scene.sheared:
            _assert_splits(path, copy, scene.world[path])
        expected = {("object", path, 0), ("bounds mesh", path, 0)}
        if copy.shear is not None:
            expected.add(("shear parent", path, 0))
        resources = plan.resources  # each read builds the tuple anew
        (partition,) = (p for p in plan.partitions if copy.object in p.resources)
        assert {
            (resources[r].role, resources[r].entity, resources[r].object_index_in_copy) for r in partition.resources
        } == expected
        used = {resources[u].role for u in resources[copy.object].dependency_resource_indices}
        assert used == {role for role, _, _ in expected if role != "object"}, path


def test_a_reflection_in_a_sheared_copy_moves_into_a_negative_scale(stress: appearance.StressScene) -> None:
    # UnitA's and UnitC's leaves are sheared and mirrored, so one part of each split must take the reflection.
    shown = copies(plan_at(stress.stage, 0.0))
    both = stress.sheared & stress.negative
    assert both
    for path in both:
        split = shown[path].shear
        assert split is not None
        parent, basis = split
        assert parent.GetDeterminant3() < 0 < basis.GetDeterminant3(), path


def test_a_projective_matrix_places_its_mesh_by_its_affine_part(transforms: evaluation.TransformsScene) -> None:
    # XFORM-05 on F-TRANSFORMS' projective layer; its approximation diagnostic is C6's.
    shown = copies(plan_at(transforms.projective_stage, 0.0))
    expected = {transforms.projective: transforms.projective_affine, **transforms.projective_instanced}
    assert shown.keys() == expected.keys()
    for path, world in expected.items():
        assert shown[path].world.GetColumn(3) == Gf.Vec4d(0, 0, 0, 1), path
        assert_world(shown[path], world)
