"""Layers are displayed as loaded and reloaded only on request (LAYER-01 to LAYER-07), for both kinds of source.

For an attached source, the dirty-layer fixture's caller is the attached stage; for a file source,
it is another tool's stage on the same files. The metamorphic check: after a reload, the binding's
evaluation stage composes what a stage newly opened from the same files composes. The new stage
opens a copy of the files, so it reads them from disk rather than sharing the reread layers.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import pytest
from pxr import Sdf, Tf, Usd

from fixtures import source_access
from fixtures.scenes import Scene, copy_scene
from fixtures.source_access import caller_settings, read_values, rewrite_on_disk
from proscenium.core.source_access import FileBindingSource, FileSource, PayloadPolicy, dirty_layers
from support.usd import open_fresh

from .bindings import KINDS, binding

# Layer file -> path of the one attribute value it authors (fixtures/source_access.py).
AUTHORED = {
    "ref": "/Asset.refValue",
    "pay": "/Asset.payValue",
    "var_a": "/Asset.varAValue",
    "var_b": "/Asset.varBValue",
}


def _value(path: Path, name: str) -> float:
    return Sdf.Layer.Find(str(path)).GetAttributeAtPath(AUTHORED[name]).default


def _fresh_values(session: Sdf.Layer, scene: Path, copy: Path) -> dict[str, float | None]:
    """What a stage newly opened from copies of scene's files composes, with session's opinions."""
    shutil.copytree(scene, copy)
    fresh = open_fresh(copy / "root.usda")
    fresh.GetSessionLayer().TransferContent(session)
    return read_values(fresh)


def _set_root_value_in_session(stage: Usd.Stage, value: float) -> None:
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        stage.GetPrimAtPath("/World").GetAttribute("rootValue").Set(value)


def _notices(*stages: Usd.Stage) -> tuple[list[object], list[Tf.Notice.Listener]]:
    """Change notices from the given stages, collected until the listeners are revoked."""
    notices: list[object] = []
    listeners = [
        Tf.Notice.Register(Usd.Notice.ObjectsChanged, lambda notice, _: notices.append(notice), stage)
        for stage in stages
    ]
    return notices, listeners


# --- as loaded ----------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_layers_are_displayed_as_loaded(kind: str, tmp_path: Path) -> None:
    # F-DIRTY-LAYER "as-loaded" (LAYER-01): unsaved edits are composed, sub.usda keeps its loaded value though its
    # file was rewritten, and acquiring again reloads nothing.
    with source_access.dirty_layer(tmp_path) as scene:
        source = binding(kind, scene.root, scene.caller)
        stage = source.acquire(PayloadPolicy.LOAD_ALL)
        assert read_values(stage) == scene.in_process_values
        assert scene.disk_values["sub"] != scene.in_process_values["sub"]
        notices, listeners = _notices(stage, scene.caller)
        source.acquire(PayloadPolicy.LOAD_ALL)
        for listener in listeners:
            listener.Revoke()
        assert notices == []
        assert all(Sdf.Layer.Find(str(path)).dirty for path in scene.dirty_contributing.values())


@pytest.mark.parametrize("kind", KINDS)
def test_dirty_layers_are_the_dirty_contributing_ones(kind: str, tmp_path: Path) -> None:
    # The layers LAYER-02's diagnostic names: ref, pay, and var_a under load-all; under load-none pay.usda,
    # reached only through unloaded payloads, drops out. var_b is dirty but never contributes.
    with source_access.dirty_layer(tmp_path) as scene:
        for payload_policy, expected in [
            (PayloadPolicy.LOAD_ALL, set(scene.dirty_contributing.values())),
            (PayloadPolicy.LOAD_NONE, {scene.dirty_contributing["ref"], scene.dirty_contributing["var_a"]}),
        ]:
            stage = binding(kind, scene.root, scene.caller).acquire(payload_policy)
            assert {Path(identifier) for identifier in dirty_layers(stage)} == expected


# --- reloading on request -----------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_reload(kind: str, tmp_path: Path) -> None:
    # F-DIRTY-LAYER "reload": the disk content under the source stage's session-layer opinion, the dirty
    # contributing layers' edits discarded, var_b's kept, and the caller's stage sees it too.
    with source_access.dirty_layer(tmp_path / "scene") as scene:
        source = binding(kind, scene.root, scene.caller)
        source.acquire(PayloadPolicy.LOAD_ALL)
        live = source.live_stage
        assert live is not None
        _set_root_value_in_session(live, 4.0)
        settings = caller_settings(scene.caller)
        source.reload(PayloadPolicy.LOAD_ALL)
        stage = source.acquire(PayloadPolicy.LOAD_ALL)
        assert read_values(stage) == scene.disk_values | {"root": 4.0}  # LAYER-03
        for name, path in scene.dirty_contributing.items():
            assert not Sdf.Layer.Find(str(path)).dirty
            assert _value(path, name) == 1.0
        var_b = scene.dirty_not_contributing["var_b"]
        assert Sdf.Layer.Find(str(var_b)).dirty
        assert _value(var_b, "var_b") == 99.0
        # LAYER-06; for an attached source the caller's stage is the source stage, with the session opinion.
        session = {"root": 4.0} if kind == "attached" else {}
        assert read_values(scene.caller) == scene.disk_values | session
        assert caller_settings(scene.caller) == settings
        fresh = _fresh_values(live.GetSessionLayer(), scene.root.parent, tmp_path / "fresh")
        assert read_values(stage) == fresh  # LAYER-07


@pytest.mark.parametrize("kind", KINDS)
def test_reload_under_load_none_leaves_payload_only_layers(kind: str, tmp_path: Path) -> None:
    # LAYER-04: pay.usda contributes only through unloaded payloads.
    with source_access.dirty_layer(tmp_path) as scene:
        binding(kind, scene.root, scene.caller).reload(PayloadPolicy.LOAD_NONE)
        pay = scene.dirty_contributing["pay"]
        assert Sdf.Layer.Find(str(pay)).dirty
        assert _value(pay, "pay") == 99.0
        assert [_value(scene.dirty_contributing[name], name) for name in ("ref", "var_a")] == [1.0, 1.0]


@pytest.mark.parametrize("kind", KINDS)
def test_reload_named_layers(kind: str, tmp_path: Path) -> None:
    # LAYER-05: only the named contributing layers; naming any other layer raises and reloads nothing.
    with source_access.dirty_layer(tmp_path) as scene:
        source = binding(kind, scene.root, scene.caller)
        stage = source.acquire(PayloadPolicy.LOAD_ALL)
        sub = Sdf.Layer.Find(str(scene.changed_on_disk["sub"])).identifier
        others = [
            Sdf.Layer.Find(str(scene.dirty_not_contributing["var_b"])).identifier,
            stage.GetSessionLayer().identifier,  # anonymous
            str(tmp_path / "unknown.usda"),
        ]
        for other in others:
            for layers in ([other], [sub, other]):
                with pytest.raises(ValueError, match="Not contributing layers"):
                    source.reload(PayloadPolicy.LOAD_ALL, layers)
                assert read_values(stage) == scene.in_process_values
        source.reload(PayloadPolicy.LOAD_ALL, [sub])
        assert read_values(stage) == scene.in_process_values | {"sub": scene.disk_values["sub"]}
        assert all(Sdf.Layer.Find(str(path)).dirty for path in scene.dirty_contributing.values())


@pytest.mark.parametrize("kind", KINDS)
def test_unchanged_layers_are_not_reloaded(kind: str, tmp_path: Path) -> None:
    # A forced reload would notify every stage using the layer even when nothing changed.
    root = copy_scene(Scene.SOURCE_ACCESS, tmp_path) / "root.usda"
    caller = open_fresh(root)  # the attached stage, or another tool holding the same layers
    source = binding(kind, root, caller)
    notices, listeners = _notices(source.acquire(PayloadPolicy.LOAD_ALL), caller)
    source.reload(PayloadPolicy.LOAD_ALL)
    for listener in listeners:
        listener.Revoke()
    assert notices == []


@pytest.mark.parametrize("kind", KINDS)
def test_layer_brought_in_by_a_reload_is_reloaded(kind: str, tmp_path: Path) -> None:
    # The root's variant selection changes on disk, bringing in var_b.usda, which another tool
    # read before its file changed.
    scene = copy_scene(Scene.SOURCE_ACCESS, tmp_path)
    held = Sdf.Layer.FindOrOpen(str(scene / "var_b.usda"))
    rewrite_on_disk(scene, "var_b", 2.0)
    caller = open_fresh(scene / "root.usda")
    source = binding(kind, scene / "root.usda", caller)
    source.acquire(PayloadPolicy.LOAD_ALL)
    root = Sdf.Layer.OpenAsAnonymous(str(scene / "root.usda"))
    root.GetPrimAtPath("/World/Var").variantSelections["option"] = "b"
    mtime_ns = (scene / "root.usda").stat().st_mtime_ns + 2_000_000_000
    root.Export(str(scene / "root.usda"))
    os.utime(scene / "root.usda", ns=(mtime_ns, mtime_ns))
    source.reload(PayloadPolicy.LOAD_ALL)
    assert read_values(source.acquire(PayloadPolicy.LOAD_ALL))["varB"] == 2.0
    assert held.GetAttributeAtPath("/Asset.varBValue").default == 2.0


@pytest.mark.parametrize("kind", KINDS)
def test_rewrite_within_the_same_second(kind: str, tmp_path: Path) -> None:
    # Expected, as in USD itself: USD's Windows timestamps have whole seconds, so a rewrite within the
    # second of the last read isn't reloaded there (runtime-record.md#windows-x64). If USD changes, this fails.
    scene = copy_scene(Scene.SOURCE_ACCESS, tmp_path)
    sub = scene / "sub.usda"
    second = (time.time_ns() - 10_000_000_000) // 1_000_000_000 * 1_000_000_000
    os.utime(sub, ns=(second + 100_000_000, second + 100_000_000))
    caller = open_fresh(scene / "root.usda")
    source = binding(kind, scene / "root.usda", caller)
    source.acquire(PayloadPolicy.LOAD_ALL)
    rewrite_on_disk(scene, "sub", 3.0)
    os.utime(sub, ns=(second + 600_000_000, second + 600_000_000))
    source.reload(PayloadPolicy.LOAD_ALL)
    assert read_values(source.acquire(PayloadPolicy.LOAD_ALL))["sub"] == (1.0 if sys.platform == "win32" else 3.0)


def test_shared_reload(tmp_path: Path) -> None:
    # F-CACHED-STAGE "shared-reload": a rewrite isn't shown until a reload, which the cached ambient stage
    # sees too, with its own settings unchanged.
    with source_access.cached_stage(tmp_path / "scene") as scene:
        source = FileBindingSource(FileSource(scene.root))
        source.acquire(PayloadPolicy.LOAD_ALL)
        settings = caller_settings(scene.ambient)
        rewrite_on_disk(scene.root.parent, "sub", 2.0)
        assert read_values(source.acquire(PayloadPolicy.LOAD_ALL))["sub"] == 1.0  # LAYER-01: not reloaded by acquiring
        source.reload(PayloadPolicy.LOAD_ALL)
        stage = source.acquire(PayloadPolicy.LOAD_ALL)
        assert read_values(stage) == scene.disk_values | {"sub": 2.0}
        assert read_values(scene.ambient) == scene.ambient_values | {"sub": 2.0}
        assert caller_settings(scene.ambient) == settings
        assert read_values(stage) == _fresh_values(stage.GetSessionLayer(), scene.root.parent, tmp_path / "fresh")
