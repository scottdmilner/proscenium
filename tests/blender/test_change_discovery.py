"""Change discovery proposes work, and comparing plans decides what a refresh writes (incremental.md; M7 plan, C7).

On F-SAME-VALUES, a synchronization at another time code acts on exactly the copies whose values differ there, in
place, and between time codes where every value is equal writes no display resource (DISC-04, AFF-03, CHG-21). On
F-EDIT-SEQUENCE, an edit undone before a refresh displays as before, a refresh after the kept chain is released acts on
what changed, as one from the kept chain does, and notices naming prims whose state didn't change write only what the
comparison finds changed (DISC-07, DISC-08). Coalesced edits are F-EDIT-SEQUENCE's coalesced-transform step
(test_edit_sequence_refresh.py), a miss recovered by a full rebuild test_full_rebuild.py's, and a miss reported by
verification test_capture_verification.py's. Each refresh is checked by support/refresh_checks.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import pytest
from pxr import Gf, Sdf, Usd, UsdGeom

from fixtures import edit_sequence, incremental
from proscenium.binding.results import ResultState
from proscenium.core import _core
from support.refresh_checks import refresh_acting_on

if TYPE_CHECKING:
    from pathlib import Path

    from proscenium.api.bindings import BindingHandle, Bindings


def _time_code(time_code: float | None) -> Usd.TimeCode:
    return Usd.TimeCode.Default() if time_code is None else Usd.TimeCode(time_code)


def _binding(bindings: Bindings, stage: Usd.Stage, time_code: Usd.TimeCode | float = 0.0) -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
    assert handle.attach(stage).state is not ResultState.FATAL_FAILURE
    assert handle.synchronize(time_code).state is not ResultState.FATAL_FAILURE
    return handle


def test_equal_time_codes_write_no_resource(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # DISC-04, AFF-03, CHG-21 on F-SAME-VALUES "equal-values": synchronized at one of each pair, then at the other,
    # where every copy evaluates the same, the second writes no display resource and keeps every datablock.
    with incremental.same_values(tmp_path) as scene:
        for first, second in scene.equal_time_codes:
            handle = _binding(bindings, scene.stage, _time_code(first))
            label = f"{first} then {second}"
            refresh_acting_on(bindings, handle, scene.stage, monkeypatch, label, time_code=_time_code(second))
            bindings.release(handle.binding_id)


@pytest.mark.parametrize(("first", "second"), [(0.0, 5.0), (5.0, 15.0), (15.0, 20.0)])
def test_differing_time_codes_update_what_differs(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first: float, second: float
) -> None:
    # CHG-14, CHG-15, CHG-21 on F-SAME-VALUES "differing-values": Held moves only where its value differs, Blink's hide
    # flags change only across 10 or 20, each in place, and Still is never written.
    with incremental.same_values(tmp_path) as scene:
        handle = _binding(bindings, scene.stage, first)
        changed = scene.changed_copies(first, second)
        assert changed  # each pair differs in some copy
        label = f"{first} then {second}"
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, label, updated=changed, time_code=second)


def test_an_edit_undone_before_a_refresh_displays_as_before(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # DISC-07: A moved and moved back before one refresh: the refresh acts on no copy.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        translate = scene.stage.GetAttributeAtPath(f"{edit_sequence.A}.xformOp:translate")
        original = translate.Get()
        translate.Set(Gf.Vec3d(3, 0, 0))
        translate.Set(original)
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "undone")


def test_a_refresh_after_the_kept_chain_is_released_acts_on_what_changed(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # DISC-07: A moved, then the kept chain released: the refresh captures from a new chain, and still updates only A.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        stages = bindings.stages.get(handle.binding_id)
        assert stages is not None
        released = stages.kept_chain
        scene.stage.GetAttributeAtPath(f"{edit_sequence.A}.xformOp:translate").Set(Gf.Vec3d(3, 0, 0))
        stages.release_kept_chain()
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "new chain", updated={edit_sequence.A})
        assert stages.kept_chain is not None and stages.kept_chain is not released


def test_notices_naming_unchanged_prims_write_only_what_changed(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # DISC-08: A moved, then moved again with a display color authored on B, which Hydra dirties and M7's planning
    # doesn't read. The second capture copies more prims than the first, its notices naming B too, and each refresh
    # updates only A.
    copied: list[int] = []
    capture = _core.SceneIndexChain.capture

    def counted(chain: _core.SceneIndexChain, time_code: Usd.TimeCode | float) -> _core.Snapshot:
        snapshot = capture(chain, time_code)
        copied.append(snapshot._copied_prim_count)  # noqa: SLF001 - the core's count for tests
        return snapshot

    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        translate = scene.stage.GetAttributeAtPath(f"{edit_sequence.A}.xformOp:translate")
        monkeypatch.setattr(_core.SceneIndexChain, "capture", counted)
        translate.Set(Gf.Vec3d(3, 0, 0))
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "A moved", updated={edit_sequence.A})
        translate.Set(Gf.Vec3d(4, 0, 0))
        b = UsdGeom.PrimvarsAPI(scene.stage.GetPrimAtPath(edit_sequence.B))
        b.CreatePrimvar("displayColor", Sdf.ValueTypeNames.Color3fArray).Set([Gf.Vec3f(1, 0, 0)])
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "A moved, B noted", updated={edit_sequence.A})
        # The first of each refresh's captures is the binding's; the clean binding's is a full one.
        assert copied[2] > copied[0], copied
