"""The transaction fixture generators produce the scenes their docstrings claim, by USD's own APIs."""

from __future__ import annotations

from pathlib import Path

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom

from fixtures import transaction
from fixtures.transaction import DRAWN, EXTENT, SUB_EDITED, translation
from proscenium.binding.source_access import PayloadPolicy
from support.usd import open_fresh

LOAD = {PayloadPolicy.LOAD_ALL: Usd.Stage.LoadAll, PayloadPolicy.LOAD_NONE: Usd.Stage.LoadNone}


def _meshes(stage: Usd.Stage) -> set[str]:
    return {str(prim.GetPath()) for prim in stage.Traverse() if prim.GetTypeName() == "Mesh"}


@pytest.mark.parametrize("policy", list(PayloadPolicy))
def test_drawn_meshes_and_bounds(policy: PayloadPolicy, tmp_path: Path) -> None:
    with transaction.failed_settings(tmp_path) as scene:
        stage = open_fresh(scene.root, LOAD[policy])
        assert _meshes(stage) == DRAWN[policy]
        for path in DRAWN[policy]:
            mesh = UsdGeom.Mesh(stage.GetPrimAtPath(path))
            extent = mesh.GetExtentAttr().Get()
            assert (Gf.Vec3d(extent[0]), Gf.Vec3d(extent[1])) == EXTENT
            assert UsdGeom.Boundable.ComputeExtentFromPlugins(mesh, Usd.TimeCode.Default()) == extent


@pytest.mark.parametrize("time_code", [None, 0.0, 10.0, 20.0, 25.0])
def test_world_translations(time_code: float | None, tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        cache = UsdGeom.XformCache(Usd.TimeCode.Default() if time_code is None else Usd.TimeCode(time_code))
        for path in DRAWN[PayloadPolicy.LOAD_ALL]:
            world = cache.GetLocalToWorldTransform(scene.caller.GetPrimAtPath(path))
            assert world.ExtractTranslation() == translation(path, time_code)
            assert world.ExtractRotationMatrix() == Gf.Matrix3d(1)


def _sub_translation(stage: Usd.Stage) -> Gf.Vec3d:
    world = UsdGeom.XformCache().GetLocalToWorldTransform(stage.GetPrimAtPath("/World/Sub"))
    return world.ExtractTranslation()


def test_source_change_edit(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        # sub.usda contributes to the caller's stage, which keeps the edited layer open.
        assert scene.sub_layer.resolve() in {Path(layer.realPath).resolve() for layer in scene.caller.GetUsedLayers()}
        scene.edit()
        assert _sub_translation(scene.caller) == SUB_EDITED
        assert Sdf.Layer.Find(str(scene.sub_layer)).dirty


def test_source_change_rewrite_on_disk(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        before = scene.sub_layer.stat().st_mtime_ns
        scene.rewrite_on_disk()
        # The open layer is unchanged until reloaded, and the reload reads the change.
        assert _sub_translation(scene.caller) == translation("/World/Sub", None)
        layer = Sdf.Layer.Find(str(scene.sub_layer))
        assert not layer.dirty
        assert scene.sub_layer.stat().st_mtime_ns > before
        layer.Reload()
        assert _sub_translation(scene.caller) == SUB_EDITED


def test_preparation_cleanup_failure_counts(tmp_path: Path) -> None:
    with transaction.preparation_cleanup_failure(tmp_path) as scene:
        # Preparation fails partway, with fewer prepared than a generation holds and more than fail to dispose.
        assert len(scene.failed_disposals) < scene.prepared_before_failure
        assert scene.prepared_before_failure < transaction.resource_count(PayloadPolicy.LOAD_ALL)


def test_retirement_failure_moves_the_mover(tmp_path: Path) -> None:
    with transaction.retirement_failure(tmp_path) as scene:
        first, second = scene.time_codes
        assert translation("/World/Mover", first) != translation("/World/Mover", second)


def test_cached_time_codes_differ(tmp_path: Path) -> None:
    with transaction.cached_time_codes(tmp_path) as scene:
        times = (scene.synchronized, *scene.cached, *scene.failing)
        assert len({translation("/World/Mover", t)[0] for t in times}) == len(times)  # x is t
        assert scene.synchronized_again in scene.cached
