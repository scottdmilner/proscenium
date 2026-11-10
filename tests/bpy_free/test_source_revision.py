"""A binding's source revision and the layers that change during an evaluation (M5 plan, B3).

The revision is what a generation is compared with before cache adds to it (CACHE-05): it changes with anything
the evaluation stage evaluates, and only then. monitor_evaluation_layer_changes names the layers a change during
evaluation touched, for the attempt's diagnostic (CONS-03). Both run on F-SOURCE-CHANGE's scene.
"""

from __future__ import annotations

import gc
import subprocess
import sys
import weakref
from typing import TYPE_CHECKING

import pytest
from pxr import Sdf, Usd

from fixtures import transaction
from proscenium.binding.source_access.binding_settings import PayloadPolicy
from proscenium.binding.source_access.stages import BindingStages, SourceUnavailableError

from .attached_binding_stages import binding

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from fixtures.transaction import SourceChangeScene


def _sub(scene: SourceChangeScene) -> Sdf.Layer:
    return Sdf.Layer.Find(str(scene.sub_layer))


def _mute_sub(scene: SourceChangeScene) -> None:
    scene.caller.MuteLayer(_sub(scene).identifier)


def _hold_values(scene: SourceChangeScene) -> None:
    scene.caller.SetInterpolationType(Usd.InterpolationTypeHeld)


def _mask_world(scene: SourceChangeScene) -> None:
    scene.caller.SetPopulationMask(Usd.StagePopulationMask(["/World/Sub"]))


def test_an_unchanged_source_keeps_its_revision(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        revision = stages.source_revision
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        stages.reload(PayloadPolicy.LOAD_ALL)  # nothing on disk changed, so nothing is reread
        Sdf.CreatePrimInLayer(Sdf.Layer.CreateAnonymous(), "/Elsewhere")  # a layer the stage doesn't compose
        assert stages.source_revision == revision


def test_an_edit_changes_the_revision(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        before = stages.source_revision
        scene.edit()
        assert stages.source_revision != before


def test_a_reload_that_rereads_changes_the_revision(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        before = stages.source_revision
        scene.rewrite_on_disk()
        assert stages.source_revision == before  # not read yet
        stages.reload(PayloadPolicy.LOAD_ALL)
        assert stages.source_revision != before


@pytest.mark.parametrize("change", [_mute_sub, _hold_values, _mask_world], ids=["muting", "interpolation", "mask"])
def test_a_caller_setting_matched_at_acquisition_changes_the_revision(
    change: Callable[[SourceChangeScene], None], tmp_path: Path
) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        before = stages.source_revision
        change(scene)
        assert stages.source_revision == before  # the evaluation stage matches it at the next acquisition
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        assert stages.source_revision != before


def test_another_payload_policy_changes_the_revision(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        before = stages.source_revision
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_NONE)
        assert stages.source_revision != before


@pytest.mark.parametrize("step", ["attach again", "drop", "release and attach"])
def test_attachments_and_new_evaluation_stages_change_the_revision(step: str, tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        before = stages.source_revision
        if step == "drop":
            stages.drop_evaluation_stage()
        else:
            if step == "release and attach":
                stages.release()
            stages.attach(scene.caller)
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        assert stages.source_revision != before


def test_a_dropped_evaluation_stage_changes_the_revision_no_more(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        stages.drop_evaluation_stage()
        revision = stages.source_revision
        scene.edit()  # the caller's stage still composes sub.usda, but nothing of the binding evaluates it
        assert stages.source_revision == revision


def test_revisions_are_unique_to_their_process() -> None:
    # A generation synchronized in another session never matches: the revision there names its own process.
    script = "from proscenium.binding.source_access.stages import BindingStages; print(BindingStages().source_revision)"
    elsewhere = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
    here = BindingStages().source_revision
    assert elsewhere.stdout.strip().split(".")[0] != here.split(".")[0]


def test_the_listener_keeps_no_binding_alive(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        evaluation = weakref.ref(stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL))
        alive = weakref.ref(stages)
        del stages
        gc.collect()
        assert alive() is None
        assert evaluation() is None
        scene.edit()  # no listener is left to advance a revision


def test_changed_layers_names_the_layers_changed_while_open(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        stages.acquire_evaluation_stage(PayloadPolicy.LOAD_ALL)
        session = scene.caller.GetSessionLayer()  # the evaluation stage composes the caller's session layer too
        with stages.monitor_evaluation_layer_changes() as changed:
            assert changed == set()
            scene.edit()
            Sdf.CreatePrimInLayer(Sdf.Layer.CreateAnonymous(), "/Elsewhere")  # a layer the stage doesn't compose
        assert changed == {_sub(scene).identifier}
        with stages.monitor_evaluation_layer_changes() as changed:
            session.comment = "edited"
        _sub(scene).GetAttributeAtPath("/World/Sub.xformOp:translate").default = (0, 0, 0)  # after: not gathered
        assert changed == {session.identifier}


def test_changed_layers_needs_an_evaluation_stage(tmp_path: Path) -> None:
    with transaction.source_change(tmp_path) as scene:
        stages = binding(scene.caller)
        with pytest.raises(SourceUnavailableError), stages.monitor_evaluation_layer_changes():
            pass
