"""A requested full rebuild, synchronize(full_rebuild=True) (API-15; DISC-07, DISC-08).

It rereads the source through a new scene-index chain, whose capture copies every prim, and prepares every partition
anew. Its display is compared by value with a clean binding's on the same stage, synchronized once
(support/clean_rebuild.py). A miss is made by the planner's test hook, which makes the kept chain's next capture drop
the notices it takes, so it shares what they named.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
from pxr import Gf

from fixtures import edit_sequence, incremental
from proscenium_sync import planner
from proscenium_sync.persistence import id_property_records
from proscenium_sync.results import ResultState
from proscenium_sync.runtime import ownership
from support.clean_rebuild import clean_rebuild, display_state

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from pxr import Usd

    from proscenium_sync.bindings import BindingHandle, Bindings


def _binding(bindings: Bindings, stage: Usd.Stage, name: str) -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name=name)
    assert handle.attach(stage).state is not ResultState.FATAL_FAILURE
    return handle


def _kept(bindings: Bindings, handle: BindingHandle) -> planner.SceneIndexChain:
    stages = bindings.stages.get(handle.binding_id)
    assert stages is not None
    chain = stages.kept_chain
    assert isinstance(chain, planner.SceneIndexChain)
    return chain


def _managed(handle: BindingHandle) -> set[int]:
    manifest = ownership.manifest(handle.binding_id)
    assert isinstance(manifest, id_property_records.LoadedRecord)
    return {e.datablock.session_uid for e in manifest.record.entries.values() if e.datablock is not None}


def test_a_full_rebuild_rereads_and_rebuilds_everything(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On F-NO-OP-REFRESH: a new chain, whose capture copies every prim, and every datablock new, with the display a
    # clean first synchronization's.
    with incremental.no_op_refresh(tmp_path) as scene:
        handle = _binding(bindings, scene.stage, "Shot")
        capture = planner.SceneIndexChain.capture
        copied: list[int] = []

        def counting(chain: planner.SceneIndexChain, time_code: Usd.TimeCode) -> planner.Snapshot:
            snapshot = capture(chain, time_code)
            copied.append(snapshot._copied_prim_count)  # noqa: SLF001 - the planner exposes it for tests only
            return snapshot

        with monkeypatch.context() as patch:  # not monkeypatch.undo(), which would undo the bindings fixture's too
            patch.setattr(planner.SceneIndexChain, "capture", counting)
            assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
            first, before = _kept(bindings, handle), _managed(handle)
            assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
            assert handle.synchronize(0, full_rebuild=True).state is not ResultState.FATAL_FAILURE
        everything, unchanged, rebuilt = copied
        assert (unchanged, rebuilt) == (0, everything)
        assert first.released
        assert _kept(bindings, handle) is not first
        assert before.isdisjoint(_managed(handle))
        assert display_state(handle.binding_id) == clean_rebuild(bindings, scene.stage)


def test_a_full_rebuild_recovers_from_a_missed_edit(bindings: Bindings, tmp_path: Path) -> None:
    # DISC-07, DISC-08 on F-EDIT-SEQUENCE: an edit the kept chain is made to miss stays undisplayed by a refresh, and a
    # requested full rebuild displays it, as a clean binding does.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage, "Shot")
        assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        before = display_state(handle.binding_id)
        scene.stage.GetAttributeAtPath(f"{edit_sequence.A}.xformOp:translate").Set(Gf.Vec3d(1, 0, 0))
        _kept(bindings, handle)._drop_next_capture_notices()  # noqa: SLF001 - the planner's test hook for a miss
        assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        assert display_state(handle.binding_id) == before  # missed
        assert handle.synchronize(0, full_rebuild=True).state is not ResultState.FATAL_FAILURE
        shown = display_state(handle.binding_id)
        assert shown != before
        assert shown == clean_rebuild(bindings, scene.stage)
