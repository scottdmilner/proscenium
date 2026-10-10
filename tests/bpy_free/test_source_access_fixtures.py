"""The source-access fixture generators produce the state their docstrings claim."""

from __future__ import annotations

from pathlib import Path

from pxr import Sdf, Usd

from fixtures import source_access
from fixtures.scenes import Scene, copy_scene
from fixtures.source_access import DISK, read_values
from support.usd import open_fresh


def _layer_on_disk(path: Path, prim: str, attr: str) -> float:
    # OpenAsAnonymous reads the file without using the shared layer. Keep the layer
    # referenced while reading: specs of a released layer are invalid.
    layer = Sdf.Layer.OpenAsAnonymous(str(path))
    return layer.GetAttributeAtPath(f"{prim}.{attr}").default


def test_unedited_scene_composes_disk_values(tmp_path: Path) -> None:
    stage = open_fresh(copy_scene(Scene.SOURCE_ACCESS, tmp_path) / "root.usda")
    assert read_values(stage) == DISK


def _dirty_used_layers(stage: Usd.Stage) -> set[Path]:
    return {Path(layer.realPath) for layer in stage.GetUsedLayers() if layer.dirty}


def test_dirty_layer(tmp_path: Path) -> None:
    with source_access.dirty_layer(tmp_path) as scene:
        assert _dirty_used_layers(scene.caller) == set(scene.dirty_contributing.values())
        assert read_values(scene.caller) == scene.in_process_values
        # Files on disk keep their values: unsaved edits were not written, the rewrite was.
        assert _layer_on_disk(scene.dirty_contributing["ref"], "/Asset", "refValue") == 1.0
        assert _layer_on_disk(scene.dirty_contributing["pay"], "/Asset", "payValue") == 1.0
        assert _layer_on_disk(scene.dirty_contributing["var_a"], "/Asset", "varAValue") == 1.0
        assert _layer_on_disk(scene.changed_on_disk["sub"], "/World", "subValue") == 2.0
        # A clean layer's Reload() picks up the disk change, giving the disk view of that layer.
        assert Sdf.Layer.Find(str(scene.changed_on_disk["sub"])).Reload()
        assert read_values(scene.caller)["sub"] == scene.disk_values["sub"]


def test_dirty_layer_of_unselected_variant_does_not_contribute(tmp_path: Path) -> None:
    with source_access.dirty_layer(tmp_path) as scene:
        var_b = scene.dirty_not_contributing["var_b"]
        assert Sdf.Layer.Find(str(var_b)).dirty
        assert var_b not in {Path(layer.realPath) for layer in scene.caller.GetUsedLayers()}
        assert _layer_on_disk(var_b, "/Asset", "varBValue") == 1.0


def test_dirty_payload_layer_contributes_only_when_loaded(tmp_path: Path) -> None:
    with source_access.dirty_layer(tmp_path) as scene:
        unloaded = open_fresh(scene.root, Usd.Stage.LoadNone)
        expected = {scene.dirty_contributing["ref"], scene.dirty_contributing["var_a"]}
        assert _dirty_used_layers(unloaded) == expected


def test_dirty_layer_edits_released_on_exit(tmp_path: Path) -> None:
    with source_access.dirty_layer(tmp_path) as scene:
        edited = [str(p) for p in (scene.dirty_contributing | scene.dirty_not_contributing).values()]
    del scene
    assert [path for path in edited if Sdf.Layer.Find(path)] == []


def test_private_stage_settings_differ_from_defaults(tmp_path: Path) -> None:
    with source_access.private_stage(tmp_path) as scene:
        default = source_access.caller_settings(open_fresh(scene.root))
        differing = {key for key in scene.settings if scene.settings[key] != default[key]}
        assert differing == set(scene.settings)
        assert read_values(scene.caller) == scene.caller_values
        anim = scene.caller.GetPrimAtPath("/World").GetAttribute("animValue")
        assert anim.Get(5) == scene.caller_anim_at_5
        assert source_access.caller_settings(scene.caller) == scene.settings
        assert source_access.layer_contents(scene.caller) == scene.layers
        root = scene.caller.GetRootLayer()
        assert root.dirty and "unsavedValue" not in scene.root.read_text(encoding="utf-8")


def test_cached_stage_hazard_is_active(tmp_path: Path) -> None:
    with source_access.cached_stage(tmp_path) as scene:
        # The hazard the fixture sets up: a plain open hands back the ambient stage.
        assert Usd.Stage.Open(str(scene.root)) is not None
        assert Usd.Stage.Open(str(scene.root)) == scene.ambient
        assert read_values(scene.ambient) == scene.ambient_values
        assert read_values(open_fresh(scene.root)) == scene.disk_values


def test_cached_stage_erased_on_exit(tmp_path: Path) -> None:
    from pxr import UsdUtils

    with source_access.cached_stage(tmp_path) as scene:
        cache_id = scene.cache_id
    assert not UsdUtils.StageCache.Get().Contains(cache_id)
