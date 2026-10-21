"""Independent bindings on one source, with file and attached sources (BIND-02 to BIND-04, BIND-07 to BIND-10).

USD shares layers across the process, so bindings on the same files see the same layer
state; what they must not share is a stage or its settings. All on F-MULTI-BINDING.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pxr import Sdf, Usd

from fixtures import source_access
from fixtures.source_access import ROOT_FORMATS, caller_settings, read_values, rewrite_on_disk
from proscenium.core.source_access import AttachedSource, BindingSource, FileSource, PayloadPolicy
from support.usd import open_fresh

if TYPE_CHECKING:
    from pathlib import Path

UNLOADED = {"payA": None, "payB": None}


def _file(root: Path) -> BindingSource:
    return BindingSource(FileSource(root))


def _attached(caller: Usd.Stage) -> BindingSource:
    source = AttachedSource("shot")
    source.attach(caller)
    return BindingSource(source)


def _set_root_value(stage: Usd.Stage, layer: Sdf.Layer, value: float) -> None:
    with Usd.EditContext(stage, layer):
        stage.GetPrimAtPath("/World").GetAttribute("rootValue").Set(value)


def test_root_layer_formats(tmp_path: Path) -> None:
    # BIND-02
    with source_access.multi_binding(tmp_path) as scene:
        for extension in ROOT_FORMATS:
            assert read_values(_file(scene.roots[extension]).acquire(PayloadPolicy.LOAD_ALL)) == scene.values


def test_bindings_on_one_file_have_their_own_stages(tmp_path: Path) -> None:
    # BIND-07: two bindings with the same file source, and one with a stage over that file attached.
    with source_access.multi_binding(tmp_path) as scene:
        root = scene.roots[".usda"]
        stages = [_file(root).acquire(PayloadPolicy.LOAD_ALL) for _ in range(2)]
        stages.append(_attached(scene.caller).acquire(PayloadPolicy.LOAD_ALL))
        assert all(a != b for i, a in enumerate(stages) for b in stages[i + 1 :])
        assert scene.caller not in stages


def test_payload_policies_on_one_file(tmp_path: Path) -> None:
    # BIND-04
    with source_access.multi_binding(tmp_path) as scene:
        root = scene.roots[".usda"]
        assert read_values(_file(root).acquire(PayloadPolicy.LOAD_ALL)) == scene.values
        assert read_values(_file(root).acquire(PayloadPolicy.LOAD_NONE)) == scene.values | UNLOADED
        assert read_values(_attached(scene.caller).acquire(PayloadPolicy.LOAD_NONE)) == scene.values | UNLOADED


def test_default_scope_is_the_whole_stage(tmp_path: Path) -> None:
    # BIND-08: every prim a stage opened on the files composes, payload contents included.
    with source_access.multi_binding(tmp_path) as scene:
        stage = _file(scene.roots[".usda"]).acquire(PayloadPolicy.LOAD_ALL)
        assert stage.GetPopulationMask() == Usd.StagePopulationMask.All()
        opened = open_fresh(scene.roots[".usda"])  # held: a traversal of an expired stage raises
        expected = {prim.GetPath() for prim in opened.TraverseAll()}
        assert {prim.GetPath() for prim in stage.TraverseAll()} == expected


def test_acquisition_leaves_the_source_unchanged(tmp_path: Path) -> None:
    # BIND-09: no layer dirtied or rewritten, and the authored variant selection ("a") is composed.
    with source_access.multi_binding(tmp_path) as scene:
        files = {path: path.read_bytes() for path in tmp_path.iterdir()}
        for payload_policy in PayloadPolicy:
            for root in scene.roots.values():
                stage = _file(root).acquire(payload_policy)
                assert (read_values(stage)["varA"], read_values(stage)["varB"]) == (1.0, None)
            _attached(scene.caller).acquire(payload_policy)
        assert [layer.identifier for layer in Sdf.Layer.GetLoadedLayers() if layer.dirty and not layer.anonymous] == []
        assert {path: path.read_bytes() for path in tmp_path.iterdir()} == files


def test_payload_policy_change_leaves_other_bindings(tmp_path: Path) -> None:
    # BIND-10, for the stages; tests/blender/test_bindings.py checks the other bindings' configuration.
    with source_access.multi_binding(tmp_path) as scene:
        root = scene.roots[".usda"]
        changed, other = _file(root), _file(root)
        attached = _attached(scene.caller)
        stages = [binding.acquire(PayloadPolicy.LOAD_ALL) for binding in (changed, other, attached)]
        load_set = scene.caller.GetLoadSet()
        assert changed.acquire(PayloadPolicy.LOAD_NONE) == stages[0]
        assert [binding.acquire(PayloadPolicy.LOAD_ALL) for binding in (other, attached)] == stages[1:]
        assert read_values(stages[0]) == scene.values | UNLOADED
        assert read_values(stages[1]) == read_values(stages[2]) == scene.values
        assert scene.caller.GetLoadSet() == load_set


def test_callers_unsaved_edit(tmp_path: Path) -> None:
    # BIND-03: a binding with the caller's stage attached shows the caller's unsaved root-layer edit, which
    # a stage reopened from the file wouldn't. Layers are displayed as loaded (LAYER-01), so a binding with
    # the same root as its file source shows it too; one on another root layer over the same sublayers doesn't.
    with source_access.multi_binding(tmp_path) as scene:
        root = scene.roots[".usda"]
        _set_root_value(scene.caller, scene.caller.GetRootLayer(), 6.0)
        assert read_values(_attached(scene.caller).acquire(PayloadPolicy.LOAD_ALL))["root"] == 6.0
        on_disk = Sdf.Layer.OpenAsAnonymous(str(root))
        assert on_disk.GetAttributeAtPath("/World.rootValue").default == 1.0
        assert read_values(_file(root).acquire(PayloadPolicy.LOAD_ALL))["root"] == 6.0
        assert read_values(_file(scene.roots[".usdc"]).acquire(PayloadPolicy.LOAD_ALL))["root"] == 1.0
        assert scene.caller.GetRootLayer().dirty


def test_a_reload_reaches_the_attached_binding(tmp_path: Path) -> None:
    # A reload through the file-source binding rereads the shared layer (LAYER-06): the attached binding and
    # the caller see the disk change, and the caller's settings are as they were. Until then, none of them does.
    with source_access.multi_binding(tmp_path) as scene:
        file_source, attached = _file(scene.roots[".usda"]), _attached(scene.caller)
        file_source.acquire(PayloadPolicy.LOAD_ALL)
        evaluation = attached.acquire(PayloadPolicy.LOAD_ALL)
        settings = caller_settings(scene.caller)
        rewrite_on_disk(tmp_path, "sub", 2.0)
        assert read_values(attached.acquire(PayloadPolicy.LOAD_ALL))["sub"] == 1.0
        file_source.reload(PayloadPolicy.LOAD_ALL)
        assert read_values(attached.acquire(PayloadPolicy.LOAD_ALL))["sub"] == 2.0
        assert attached.evaluation_stage == evaluation
        assert read_values(scene.caller)["sub"] == 2.0
        assert caller_settings(scene.caller) == settings


def test_callers_stage_state_stays_with_the_caller(tmp_path: Path) -> None:
    # Muting and session-layer opinions are the attached stage's own: its binding follows them, a binding
    # with the same file as its source doesn't see them.
    with source_access.multi_binding(tmp_path) as scene:
        scene.caller.MuteLayer(str(tmp_path / "extra.usda"))
        _set_root_value(scene.caller, scene.caller.GetSessionLayer(), 5.0)
        attached = read_values(_attached(scene.caller).acquire(PayloadPolicy.LOAD_ALL))
        assert (attached["extra"], attached["root"]) == (None, 5.0)
        assert read_values(_file(scene.roots[".usda"]).acquire(PayloadPolicy.LOAD_ALL)) == scene.values
