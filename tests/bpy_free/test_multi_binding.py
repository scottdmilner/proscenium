"""Independent bindings on caller-supplied stages (BIND-02 to BIND-04, BIND-07 to BIND-10).

USD shares layers across the process, so bindings on the same files see the same layer
state; each binding has its own evaluation stage and settings. All on F-MULTI-BINDING.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pxr import Sdf, Usd

from fixtures import source_access
from fixtures.source_access import ROOT_FORMATS, caller_settings, read_values, rewrite_on_disk
from proscenium.binding.source_access.stages import PayloadPolicy
from support.usd import open_fresh

from .bindings import binding

if TYPE_CHECKING:
    from pathlib import Path

UNLOADED = {"payA": None, "payB": None}


def _set_root_value(stage: Usd.Stage, layer: Sdf.Layer, value: float) -> None:
    with Usd.EditContext(stage, layer):
        stage.GetPrimAtPath("/World").GetAttribute("rootValue").Set(value)


def test_root_layer_formats(tmp_path: Path) -> None:
    # BIND-02
    with source_access.multi_binding(tmp_path) as scene:
        for extension in ROOT_FORMATS:
            caller = open_fresh(scene.roots[extension])
            assert read_values(binding(caller).acquire(PayloadPolicy.LOAD_ALL)) == scene.values


def test_bindings_on_one_source_have_their_own_evaluation_stages(tmp_path: Path) -> None:
    # BIND-07: two bindings share one source stage; a third uses another stage over the same root.
    with source_access.multi_binding(tmp_path) as scene:
        other_caller = open_fresh(scene.roots[".usda"])
        sources = (scene.caller, scene.caller, other_caller)
        stages = [binding(caller).acquire(PayloadPolicy.LOAD_ALL) for caller in sources]
        assert all(a != b for i, a in enumerate(stages) for b in stages[i + 1 :])
        assert all(stage not in sources for stage in stages)
        assert [stage.GetSessionLayer() for stage in stages] == [caller.GetSessionLayer() for caller in sources]


def test_payload_policies_on_one_source(tmp_path: Path) -> None:
    # BIND-04
    with source_access.multi_binding(tmp_path) as scene:
        assert read_values(binding(scene.caller).acquire(PayloadPolicy.LOAD_ALL)) == scene.values
        assert read_values(binding(scene.caller).acquire(PayloadPolicy.LOAD_NONE)) == scene.values | UNLOADED


def test_default_scope_is_the_whole_stage(tmp_path: Path) -> None:
    # BIND-08: every prim a stage opened on the files composes, payload contents included.
    with source_access.multi_binding(tmp_path) as scene:
        stage = binding(open_fresh(scene.roots[".usda"])).acquire(PayloadPolicy.LOAD_ALL)
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
                stage = binding(open_fresh(root)).acquire(payload_policy)
                assert (read_values(stage)["varA"], read_values(stage)["varB"]) == (1.0, None)
            binding(scene.caller).acquire(payload_policy)
        assert [layer.identifier for layer in Sdf.Layer.GetLoadedLayers() if layer.dirty and not layer.anonymous] == []
        assert {path: path.read_bytes() for path in tmp_path.iterdir()} == files


def test_payload_policy_change_leaves_other_bindings(tmp_path: Path) -> None:
    # BIND-10, for the stages; tests/blender/test_bindings.py checks the other bindings' configuration.
    with source_access.multi_binding(tmp_path) as scene:
        root = scene.roots[".usda"]
        changed, other = binding(open_fresh(root)), binding(open_fresh(root))
        attached = binding(scene.caller)
        stages = [binding.acquire(PayloadPolicy.LOAD_ALL) for binding in (changed, other, attached)]
        load_set = scene.caller.GetLoadSet()
        assert changed.acquire(PayloadPolicy.LOAD_NONE) == stages[0]
        assert [binding.acquire(PayloadPolicy.LOAD_ALL) for binding in (other, attached)] == stages[1:]
        assert read_values(stages[0]) == scene.values | UNLOADED
        assert read_values(stages[1]) == read_values(stages[2]) == scene.values
        assert scene.caller.GetLoadSet() == load_set


def test_callers_unsaved_edit(tmp_path: Path) -> None:
    # BIND-03, LAYER-01: attached stages share unsaved root-layer edits; a stage on another root does not.
    with source_access.multi_binding(tmp_path) as scene:
        root = scene.roots[".usda"]
        _set_root_value(scene.caller, scene.caller.GetRootLayer(), 6.0)
        assert read_values(binding(scene.caller).acquire(PayloadPolicy.LOAD_ALL))["root"] == 6.0
        on_disk = Sdf.Layer.OpenAsAnonymous(str(root))
        assert on_disk.GetAttributeAtPath("/World.rootValue").default == 1.0
        assert read_values(binding(open_fresh(root)).acquire(PayloadPolicy.LOAD_ALL))["root"] == 6.0
        assert read_values(binding(open_fresh(scene.roots[".usdc"])).acquire(PayloadPolicy.LOAD_ALL))["root"] == 1.0
        assert scene.caller.GetRootLayer().dirty


def test_anonymous_source_needs_no_files(tmp_path: Path) -> None:
    # BIND-03: an anonymous source and its unsaved opinions can be evaluated after the scene files are gone.
    with source_access.multi_binding(tmp_path) as scene:
        caller = scene.anonymous_caller
        _set_root_value(caller, caller.GetRootLayer(), 6.0)
        for path in tmp_path.iterdir():
            path.unlink()
        source = binding(caller)
        evaluation = source.acquire(PayloadPolicy.LOAD_ALL)
        assert source.live_stage == caller
        assert evaluation != caller
        assert read_values(evaluation) == scene.values | {"root": 6.0}
        assert evaluation.GetRootLayer() == caller.GetRootLayer()
        assert evaluation.GetSessionLayer() == caller.GetSessionLayer()
        _set_root_value(caller, caller.GetSessionLayer(), 7.0)
        assert source.acquire(PayloadPolicy.LOAD_ALL) == evaluation
        assert read_values(evaluation) == scene.values | {"root": 7.0}


def test_a_reload_reaches_the_attached_binding(tmp_path: Path) -> None:
    # LAYER-06: a reload reaches bindings and callers composing the shared layer, preserving caller settings.
    with source_access.multi_binding(tmp_path) as scene:
        reloading, attached = binding(open_fresh(scene.roots[".usda"])), binding(scene.caller)
        reloading.acquire(PayloadPolicy.LOAD_ALL)
        evaluation = attached.acquire(PayloadPolicy.LOAD_ALL)
        settings = caller_settings(scene.caller)
        rewrite_on_disk(tmp_path, "sub", 2.0)
        assert read_values(attached.acquire(PayloadPolicy.LOAD_ALL))["sub"] == 1.0
        reloading.reload(PayloadPolicy.LOAD_ALL)
        assert read_values(attached.acquire(PayloadPolicy.LOAD_ALL))["sub"] == 2.0
        assert attached.evaluation_stage == evaluation
        assert read_values(scene.caller)["sub"] == 2.0
        assert caller_settings(scene.caller) == settings


def test_callers_stage_state_stays_with_the_caller(tmp_path: Path) -> None:
    # Bindings follow their attached stage's muting and session opinions; another stage over the root is independent.
    with source_access.multi_binding(tmp_path) as scene:
        scene.caller.MuteLayer(str(tmp_path / "extra.usda"))
        _set_root_value(scene.caller, scene.caller.GetSessionLayer(), 5.0)
        attached = read_values(binding(scene.caller).acquire(PayloadPolicy.LOAD_ALL))
        assert (attached["extra"], attached["root"]) == (None, 5.0)
        assert read_values(binding(open_fresh(scene.roots[".usda"])).acquire(PayloadPolicy.LOAD_ALL)) == scene.values
