"""Drawn copies inside native instances, through the minimal plan (M6 plan, B3).

Each copy's source is its instance-proxy path on the composed stage, with its instance context, and its world
transform honors a reset transform stack inside an instance (WORKAROUND for OpenUSD #862), on F-TRANSFORMS' case
"reset-stack" (XFORM-01, XFORM-02) and F-NESTED-STRESS' "transforms" (XFORM-02, XFORM-03). Point instancers'
copies are test_core_point_instancers.py's. Expected values come from the fixtures, or from USD's own APIs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom

from fixtures import appearance, evaluation
from proscenium.binding.source_access import source_entity_ids
from proscenium.binding.source_access.stages import PayloadPolicy
from proscenium.core import _core
from support.usd import open_stage_without_cache

from .plan_checks import assert_world, copies, plan_at

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


def _contexts(plan: _core.Plan) -> dict[str, tuple[str, ...]]:
    return {c.source_path: c.instance_context for c in plan.correspondence}


def _usd_context(stage: Usd.Stage, path: str) -> tuple[str, ...]:
    """The native-instance roots `path` lies in, outermost first, from USD."""
    roots: list[str] = []
    ancestor = stage.GetPrimAtPath(path).GetParent()
    while ancestor and not ancestor.IsPseudoRoot():
        if ancestor.IsInstance():
            roots.append(str(ancestor.GetPath()))
        ancestor = ancestor.GetParent()
    return tuple(reversed(roots))


@pytest.mark.parametrize("policy", list(PayloadPolicy))
def test_transforms_copies_and_contexts(policy: PayloadPolicy, transforms: evaluation.TransformsScene) -> None:
    # Under each payload policy, F-TRANSFORMS holding a payload (AFIX-06).
    plan = plan_at(open_stage_without_cache(transforms.root_layer_path, evaluation.LOAD[policy]), 0.0)
    shown = copies(plan)
    assert set(shown) == transforms.drawn(policy)
    for path, copy in shown.items():
        assert_world(copy, transforms.world_at(path, 0.0))
    assert _contexts(plan) == {path: transforms.instance_context.get(path, ()) for path in transforms.drawn(policy)}


def test_nested_copies_and_contexts(stress: appearance.StressScene) -> None:
    plan = plan_at(stress.stage, 0.0)
    shown = copies(plan)
    assert (
        set(shown) == stress.viewport_paths | stress.render_paths
    )  # its guides, never explicitly visible, leave the plan
    for path, copy in shown.items():
        assert_world(copy, stress.world_matrices_by_source[path])
    contexts = _contexts(plan)
    assert contexts == {path: _usd_context(stress.stage, path) for path in shown}
    assert max(len(c) for c in contexts.values()) == 2  # nested instances, so the check above covers nesting


def test_copies_of_a_mesh_share_its_geometry_description(stress: appearance.StressScene) -> None:
    # Provisional (M8 keys a mesh by its content): one description per mesh Hydra draws. Hydra may split one USD
    # prototype into several of its own, so copies sharing a description are copies of one USD prototype mesh, not the
    # converse.
    plan = plan_at(stress.stage, 0.0)
    shown = copies(plan)
    sharing: dict[int, list[str]] = {}
    for path, copy in shown.items():
        assert stress.stage.GetPrimAtPath(path).GetTypeName() == "Mesh", path
        assert (copy.geometry_index >= 0, copy.placeholder_bounds_index) == (True, -1), path
        sharing.setdefault(copy.geometry_index, []).append(path)
    assert sorted(sharing) == list(range(len(plan.geometries)))
    assert len(plan.geometries) < len(shown)  # some copies share, so the checks below could fail
    for geometry, paths in sharing.items():
        description = plan.geometries[geometry]
        assert description.representative_source_path == min(paths)  # its first copy's, in source order
        assert description.content_key == description.representative_source_path
        prims = [stress.stage.GetPrimAtPath(p) for p in paths]
        assert len({p.GetPrimInPrototype().GetPath() if p.IsInstanceProxy() else p.GetPath() for p in prims}) == 1
        extent = UsdGeom.Mesh(prims[0]).GetExtentAttr().Get(Usd.TimeCode(0.0))
        assert memoryview(description.extent).tolist() == [*extent[0], *extent[1]]


def test_instanced_copies_are_identified_by_instance_proxy_paths(stress: appearance.StressScene) -> None:
    plan = plan_at(stress.stage, 0.0)
    for resource in plan.resources:
        assert resource.source_entity_paths == (resource.source_entity_path,)
        assert source_entity_ids.identifier(Sdf.Path(resource.source_entity_path)) == resource.source_entity_path
        assert stress.stage.GetPrimAtPath(resource.source_entity_path).IsInstanceProxy(), resource.source_entity_path


def test_known_gap_hydra_ignores_a_reset_inside_an_instance(stress: appearance.StressScene) -> None:
    # WORKAROUND for OpenUSD #862 (InstanceResolver::ResetsBelow in core/instancing.h): Hydra's own composition, a
    # copy's flattened transform then its instance's, is wrong exactly for the copies under a reset inside an
    # instance. This fails once Hydra honors the reset, and the workaround can go.
    chain = _core.SceneIndexChain(stress.stage)
    try:
        hydra = _core._hydra_composed_worlds(chain.capture(Usd.TimeCode(0.0)))  # noqa: SLF001 - the known-gap hook
    finally:
        chain.release()
    cache = UsdGeom.XformCache()

    def usd(path: str) -> Gf.Matrix4d:
        return cache.GetLocalToWorldTransform(stress.stage.GetPrimAtPath(path))

    assert set(hydra) == set(stress.world_matrices_by_source)
    wrong = {path for path, world in hydra.items() if not Gf.IsClose(world, usd(path), 1e-6)}
    assert wrong == {path for path in stress.world_matrices_by_source if path.endswith("/Pinned/Pin")}
