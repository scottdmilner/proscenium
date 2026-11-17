"""A kept chain's captures copy only the prims notices named, and plan what a full re-read does (M7 plan, C2).

The oracle for each incremental capture is a full re-read: a new chain over the same stage, captured at the same time
code, whose plan must equal it in every part (plan_serialization.contents), diagnostics included. Never
HdsiComputeSceneIndexDiffDelta, which compares handles, not values. A capture's copied-prim count, which the core
exposes for tests only, shows how much it shared.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Gf, Usd, UsdGeom, Vt

from fixtures import edit_sequence, evaluation, time_variations
from proscenium_sync import core

from . import plan_serialization

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

DEFAULT = core.PlanSettings(("default", "proxy"), ("default", "render"), coordinate_conversion=False)
WITH_GUIDES = core.PlanSettings(("default", "proxy", "guide"), ("default", "render"), coordinate_conversion=False)
CONTEXT = core.PlanningContext(1.0, 1)


def _copied(snapshot: core.Snapshot) -> int:
    return snapshot._copied_prim_count  # noqa: SLF001 - the core exposes it for tests and measurements only


def _full_plan(stage: Usd.Stage, time_code: float, settings: core.PlanSettings) -> dict[str, object]:
    """What a new chain over stage plans at time_code: the oracle."""
    chain = core.SceneIndexChain(stage)
    try:
        return plan_serialization.contents(core.plan(chain.capture(Usd.TimeCode(time_code)), settings, CONTEXT))
    finally:
        chain.release()


class _KeptChain:
    """A chain kept over stage, as a binding keeps one, each capture compared with a full re-read."""

    def __init__(self, stage: Usd.Stage, settings: core.PlanSettings = DEFAULT) -> None:
        self.stage, self.settings = stage, settings
        self.chain = core.SceneIndexChain(stage)
        self.prim_count = _copied(self.chain.capture(Usd.TimeCode(0)))  # the first copies every prim

    def capture(self, time_code: float = 0.0) -> tuple[dict[str, object], int]:
        """The plan of a capture at time_code, checked against a full re-read, and how many prims it copied."""
        snapshot = self.chain.capture(Usd.TimeCode(time_code))
        planned = plan_serialization.contents(core.plan(snapshot, self.settings, CONTEXT))
        assert planned == _full_plan(self.stage, time_code, self.settings)
        return planned, _copied(snapshot)

    def release(self) -> None:
        self.chain.release()


def test_a_capture_with_nothing_changed_copies_nothing(tmp_path: Path) -> None:
    with edit_sequence.edit_sequence(tmp_path) as scene:
        kept = _KeptChain(scene.stage)
        try:
            assert kept.prim_count > 0
            assert kept.capture()[1] == 0
        finally:
            kept.release()


def test_each_edit_of_the_sequence_equals_a_full_re_read(tmp_path: Path) -> None:
    # TINC-01's capture half, on F-EDIT-SEQUENCE: each step applied in order to one stage, captured from one chain. A
    # step whose edit changes the display changes the plan, and an edit to one prim's state copies only a few prims.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        kept = _KeptChain(scene.stage)
        try:
            before, _ = kept.capture()
            for step in scene.steps:
                step.edit(scene.stage)
                planned, copied = kept.capture()
                assert copied < kept.prim_count, step.name
                if step.updated or step.rebuilt or step.retired or step.built:
                    assert planned != before, step.name
                before = planned
        finally:
            kept.release()


def test_coalesced_and_undone_edits_equal_a_full_re_read(tmp_path: Path) -> None:
    # Two edits between captures, and an edit undone before one (DISC-07's coalesced notices).
    with edit_sequence.edit_sequence(tmp_path) as scene:
        kept = _KeptChain(scene.stage)
        translate = scene.stage.GetAttributeAtPath(f"{edit_sequence.A}.xformOp:translate")
        original = translate.Get()
        try:
            translate.Set(Gf.Vec3d(1, 0, 0))
            translate.Set(Gf.Vec3d(2, 0, 0))
            moved, _ = kept.capture()
            translate.Set(Gf.Vec3d(3, 0, 0))
            translate.Set(original)
            restored, _ = kept.capture()
            assert moved != restored
            assert restored == _full_plan(scene.stage, 0.0, DEFAULT)
        finally:
            kept.release()


def test_time_changes_equal_a_full_re_read(tmp_path: Path) -> None:
    # On F-TIME-VARIATIONS, captures moving back and forth across its transitions: a time change copies only what
    # varies, and a capture at the same time code again copies nothing.
    with time_variations.time_variations(tmp_path) as scene:
        kept = _KeptChain(scene.stage)
        try:
            for time_code in (5.0, 10.0, 15.0, 20.0, 15.0, 0.0, 12.0):
                _, copied = kept.capture(time_code)
                assert 0 < copied < kept.prim_count, time_code
                assert kept.capture(time_code)[1] == 0
        finally:
            kept.release()


def _hide_guides(stage: Usd.Stage) -> None:
    # Applying VisibilityAPI resyncs the prim, which Hydra reports, so it's applied before the chain is built.
    UsdGeom.VisibilityAPI.Apply(stage.GetPrimAtPath("/World/Shown")).CreateGuideVisibilityAttr("invisible")


def _show_guides(stage: Usd.Stage) -> None:
    UsdGeom.VisibilityAPI(stage.GetPrimAtPath("/World/Shown")).GetGuideVisibilityAttr().Set("visible")


def _nothing(_stage: Usd.Stage) -> None:
    pass


def _move_tangents(stage: Usd.Stage) -> None:
    stage.GetAttributeAtPath("/World/Tangents.xformOp:translate").Set(Gf.Vec3d(10, 1, 0))


def _widen_combed(stage: Usd.Stage) -> None:
    stage.GetAttributeAtPath("/World/Combed.widths").Set(Vt.FloatArray([2.0]))


def _renumber_tagged(stage: Usd.Stage) -> None:
    stage.GetAttributeAtPath("/World/Tagged.ids").Set(Vt.Int64Array([11, -3, 7, 12]))


# Edits to what the source-info filter adds. Hydra doesn't dirty an Xform's authored guide visibility, which its Guide
# mesh inherits, or a point instancer's ids, so only the filter's stage listener names them; without it, both fail.
# Hydra itself names the other two, a transform of HermiteCurves, which it doesn't image, and the widths a computed
# extent follows, which it dirties as primvars, and the listener names them too.
type StageEdit = Callable[[Usd.Stage], None]
type ListenedCase = tuple[Callable[[Path], object], StageEdit, StageEdit, core.PlanSettings]  # with a setup
LISTENED: dict[str, ListenedCase] = {
    "guide visibility": (evaluation.visibility_purpose, _hide_guides, _show_guides, WITH_GUIDES),
    "unimaged transform": (evaluation.unsupported_content, _nothing, _move_tangents, DEFAULT),
    "computed extent": (evaluation.unsupported_content, _nothing, _widen_combed, DEFAULT),
    "point ids": (evaluation.point_instancers, _nothing, _renumber_tagged, DEFAULT),
}


@pytest.mark.parametrize("case", LISTENED.values(), ids=LISTENED.keys())
def test_edits_hydra_doesnt_dirty_equal_a_full_re_read(case: ListenedCase, tmp_path: Path) -> None:
    generator, setup, edit, settings = case
    with generator(tmp_path) as scene:  # ty: ignore[invalid-context-manager] - each generator is a context manager
        setup(scene.stage)
        kept = _KeptChain(scene.stage, settings)
        try:
            before, _ = kept.capture()
            edit(scene.stage)
            planned, copied = kept.capture()
            assert planned != before
            assert 0 < copied < kept.prim_count
        finally:
            kept.release()


def test_a_shared_prim_keeps_its_diagnostics(tmp_path: Path) -> None:
    # F-UNSUPPORTED-CONTENT's prims each have diagnostics; an edit to one leaves the others' in the plan, as a full
    # re-read reports them (the comparison includes diagnostics).
    with evaluation.unsupported_content(tmp_path) as scene:
        kept = _KeptChain(scene.stage)
        try:
            before, _ = kept.capture()
            _move_tangents(scene.stage)
            planned, _ = kept.capture()
            assert before["diagnostics"]
            assert planned["diagnostics"] == before["diagnostics"]
        finally:
            kept.release()
