"""The opt-in verification mode, PROSCENIUM_VERIFY_CAPTURE (DIAG-17; M7 plan, C3c).

With it set, a capture from the binding's kept chain is also made through a new chain, and where their plans differ the
new one's is displayed, its chain kept instead, and each differing drawn copy reported as a verification diagnostic,
which leaves the result state alone. A miss is made by the core's test hook, which makes the kept chain's next capture
drop the notices it takes. Displays are compared by value with a clean binding's on the same stage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
from pxr import Gf, Usd

from fixtures import appearance, edit_sequence
from proscenium.binding.results import DiagnosticCategory, DiagnosticCode, ResultState
from proscenium.binding.source_access import BindingId
from proscenium.core import _core
from proscenium.synchronization import capture_verification
from support.displayed_copies import displayed_copies

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from proscenium.api.bindings import BindingHandle, Bindings
    from proscenium.binding.results import Diagnostic, Result
    from support.bounds_check import DisplayedCopy

A_TRANSLATE = f"{edit_sequence.A}.xformOp:translate"


def _binding(bindings: Bindings, stage: Usd.Stage, name: str) -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name=name)
    assert handle.attach(stage).state is ResultState.SUCCESS
    return handle


def _kept(bindings: Bindings, handle: BindingHandle) -> _core.SceneIndexChain:
    stages = bindings.stages.get(handle.binding_id)
    assert stages is not None
    chain = stages.kept_chain
    assert isinstance(chain, _core.SceneIndexChain)
    return chain


def _shown(handle: BindingHandle) -> list[DisplayedCopy]:
    return sorted(displayed_copies(handle.binding_id), key=lambda copy: (copy.source_path, copy.world_vertices))


def _mismatches(result: Result) -> list[Diagnostic]:
    return [d for d in result.diagnostics if d.code is DiagnosticCode.CAPTURE_MISMATCH]


def _counting_captures(monkeypatch: pytest.MonkeyPatch) -> list[_core.SceneIndexChain]:
    """The chains captured from, in order, while the patch lasts."""
    capture = _core.SceneIndexChain.capture
    captured_from: list[_core.SceneIndexChain] = []

    def recording(chain: _core.SceneIndexChain, time_code: Usd.TimeCode) -> _core.Snapshot:
        captured_from.append(chain)
        return capture(chain, time_code)

    monkeypatch.setattr(_core.SceneIndexChain, "capture", recording)
    return captured_from


def test_a_missed_edit_is_reported_and_the_full_re_read_displayed(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(capture_verification.VERIFY_CAPTURE_VARIABLE, "1")
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage, "Shot")
        assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        missing = _kept(bindings, handle)
        scene.stage.GetAttributeAtPath(A_TRANSLATE).Set(Gf.Vec3d(1, 0, 0))
        missing._drop_next_capture_notices()  # noqa: SLF001 - the core's test hook for a miss
        result = handle.synchronize(0)
        [mismatch] = _mismatches(result)
        assert (mismatch.source_path, mismatch.category) == (edit_sequence.A, DiagnosticCategory.VERIFICATION)
        assert missing.released
        assert _kept(bindings, handle) is not missing  # the full re-read's chain, kept instead
        clean = _binding(bindings, scene.stage, "Clean")
        expected = clean.synchronize(0)
        assert result.state is expected.state  # a verification diagnostic changes no result state
        assert _shown(handle) == _shown(clean)


def test_with_nothing_missed_verification_reports_nothing(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The first synchronization builds its chain, so it captures once; a later one captures from the kept chain and
    # a new one, which it then releases.
    monkeypatch.setenv(capture_verification.VERIFY_CAPTURE_VARIABLE, "1")
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage, "Shot")
        with monkeypatch.context() as patch:  # not monkeypatch.undo(), which would undo the bindings fixture's too
            captured_from = _counting_captures(patch)
            first = handle.synchronize(0)
            kept = _kept(bindings, handle)
            scene.stage.GetAttributeAtPath(A_TRANSLATE).Set(Gf.Vec3d(1, 0, 0))
            second = handle.synchronize(0)
        assert not _mismatches(first) and not _mismatches(second)
        [built, from_kept, fresh] = captured_from
        assert built is kept and from_kept is kept and fresh is not kept
        assert fresh.released
        assert _kept(bindings, handle) is kept


def test_without_the_variable_a_synchronization_captures_once(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(capture_verification.VERIFY_CAPTURE_VARIABLE, raising=False)
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage, "Shot")
        assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        with monkeypatch.context() as patch:
            captured_from = _counting_captures(patch)
            scene.stage.GetAttributeAtPath(A_TRANSLATE).Set(Gf.Vec3d(1, 0, 0))
            assert not _mismatches(handle.synchronize(0))
        assert captured_from == [_kept(bindings, handle)]


def _plan(stage: Usd.Stage) -> _core.Plan:
    chain = _core.SceneIndexChain(stage)
    try:
        settings = _core.PlanSettings(("default", "proxy"), ("default", "render"), coordinate_conversion=False)
        return _core.plan(chain.capture(Usd.TimeCode(0)), settings, _core.PlanningContext(1.0, 1))
    finally:
        chain.release()


def test_many_differing_copies_are_listed_ten_then_counted(tmp_path: Path) -> None:
    # pipeline.md#diagnostics' aggregation: F-NESTED-STRESS's copies against an empty stage's plan, which has none.
    with appearance.nested_stress(tmp_path) as stress:
        full = _plan(stress.stage)
    empty = _plan(Usd.Stage.CreateInMemory())
    assert full.copy_count > capture_verification.LISTED
    found = capture_verification.mismatch_diagnostics(BindingId("binding"), [Usd.TimeCode(0)], [empty], [full])
    named, counted = found[: capture_verification.LISTED], found[capture_verification.LISTED :]
    paths = sorted(entry.source_path for entry in full.correspondence)
    assert [d.source_path for d in named] == paths[: capture_verification.LISTED]
    [rest] = counted
    assert (rest.source_path, str(full.copy_count - capture_verification.LISTED) in rest.message) == ("", True)
