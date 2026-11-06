"""Caching time codes in the published generation, against the stub application layer (pipeline.md#cached-time-codes).

On F-CACHED-TIME-CODES (fixtures/transaction.py), M5 plan, E1. The stub keys each placeholder's transform at each
cached time code, so a frame shows the latest cached time code at or before it; expected translations come from how
the scene is built (transaction.translation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest
from pxr import Usd

from fixtures import transaction
from fixtures.transaction import translation
from proscenium.api import bindings as api
from proscenium.binding.persistence import binding_state, records
from proscenium.binding.persistence.manifests import RepresentationRole
from proscenium.binding.results import ResultState
from proscenium.binding.runtime import ownership
from support import undo

if TYPE_CHECKING:
    from pathlib import Path

    from fixtures.transaction import CachedTimeCodesScene
    from proscenium.api.bindings import BindingHandle, Bindings

MOVER = "/World/Mover"
MARKER = "Undo base"


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _synchronized(bindings: Bindings, scene: CachedTimeCodesScene) -> BindingHandle:
    handle = bindings.create_binding(_scene(), name="Shot")
    assert handle.attach(scene.caller).state is ResultState.SUCCESS
    assert handle.synchronize(scene.synchronized).state is ResultState.SUCCESS
    return handle


def _generation() -> binding_state.Generation:
    generation = binding_state.read_generation(bpy.data.collections["Shot"])
    assert isinstance(generation, records.Loaded)
    return generation.record


def _entries(handle: BindingHandle) -> dict[str, Any]:
    manifest = ownership.manifest(handle.binding_id)
    assert isinstance(manifest, records.Loaded)
    return dict(manifest.record.entries)


def _object(handle: BindingHandle, path: str) -> bpy.types.Object:
    [obj] = [
        e.datablock for e in _entries(handle).values() if e.role is RepresentationRole.OBJECT and e.covers == (path,)
    ]
    assert isinstance(obj, bpy.types.Object)
    return obj


def _shown_at(handle: BindingHandle, frame: float, path: str = MOVER) -> tuple[float, ...]:
    """The world translation of path's placeholder at frame."""
    _scene().frame_set(int(frame), subframe=frame % 1)
    return tuple(_object(handle, path).matrix_world.translation[:])


def test_cached_time_codes_show_their_values_in_the_same_generation(bindings: Bindings, tmp_path: Path) -> None:
    # CACHE-02 and API-09 on F-CACHED-TIME-CODES: the generation keeps its settings, time code, and resources, gains
    # exactly the call's time codes, and records no new last attempt; each cached time code's frame shows its values,
    # and a frame between them the latest one before it.
    with transaction.cached_time_codes(tmp_path) as scene:
        handle = _synchronized(bindings, scene)
        before, entries = _generation(), _entries(handle)
        attempt = binding_state.read_last_attempt(bpy.data.collections["Shot"])
        result = handle.cache(scene.cached)
        assert result.state is ResultState.SUCCESS
        assert result.time_codes == tuple(Usd.TimeCode(t) for t in scene.cached)
        assert _generation() == binding_state.Generation(
            before.binding_id,
            before.payload_policy,
            before.time_code,
            before.source_revision,
            before.diagnostics,
            scene.cached,
        )
        assert binding_state.read_last_attempt(bpy.data.collections["Shot"]) == attempt
        after = _entries(handle)
        assert {k: e.datablock for k, e in after.items() if k in entries} == {
            k: e.datablock for k, e in entries.items()
        }
        added = {e.role for k, e in after.items() if k not in entries}
        assert added == {RepresentationRole.ACTION}  # each object's keys, owned with it
        for time_code in (scene.synchronized, *scene.cached):
            assert _shown_at(handle, time_code) == pytest.approx(translation(MOVER, time_code))
        between = (scene.cached[0] + scene.cached[1]) / 2
        assert _shown_at(handle, between) == pytest.approx(translation(MOVER, scene.cached[0]))
        assert _shown_at(handle, scene.cached[-1], "/World/Still") == pytest.approx(translation("/World/Still", 0))
        assert not handle.possibly_out_of_date()


def test_a_call_caches_only_the_time_codes_not_yet_cached(bindings: Bindings, tmp_path: Path) -> None:
    # API-09: handle.cache and Bindings.cache take a collection, one time code included, and the result names only
    # the time codes not cached before, the generation's own among them.
    with transaction.cached_time_codes(tmp_path) as scene:
        handle = _synchronized(bindings, scene)
        first, *rest = scene.cached
        assert handle.cache([first]).time_codes == (Usd.TimeCode(first),)
        again = bindings.cache(handle.binding_id, [scene.synchronized, first, *rest])
        assert again.state is ResultState.SUCCESS
        assert again.time_codes == tuple(Usd.TimeCode(t) for t in rest)
        assert handle.cache(scene.cached).time_codes == ()
        assert _generation().cached_time_codes == scene.cached


def test_the_default_time_code_is_not_one_to_cache(bindings: Bindings, tmp_path: Path) -> None:
    # API-14 on F-CACHED-TIME-CODES: misuse raises, caching nothing.
    with transaction.cached_time_codes(tmp_path) as scene:
        handle = _synchronized(bindings, scene)
        before = _generation()
        with pytest.raises(ValueError, match="default time code"):
            handle.cache([scene.cached[0], Usd.TimeCode.Default()])
        assert _generation() == before


@pytest.mark.usefixtures("pushing")
def test_caching_pushes_no_undo_step_and_undo_restores_what_was_cached(bindings: Bindings, tmp_path: Path) -> None:
    # UNDO-09 on F-CACHED-TIME-CODES: the undo after a cache call reaches past the step before it, since it pushed
    # none; undoing the next synchronization restores the earlier generation with its cached time codes and keys, and
    # redo the later one with its own.
    with transaction.cached_time_codes(tmp_path) as scene:
        handle = _synchronized(bindings, scene)
        bpy.data.objects.new(MARKER, None)
        undo.push("base")
        assert handle.cache(scene.cached).state is ResultState.SUCCESS
        undo.undo()
        assert MARKER not in bpy.data.objects
        assert _generation().cached_time_codes == ()
        assert handle.cache(scene.cached).state is ResultState.SUCCESS
        undo.push("cached")
        assert handle.synchronize(scene.synchronized_again).state is ResultState.SUCCESS
        undo.undo()
        assert _generation().cached_time_codes == scene.cached
        for time_code in (scene.synchronized, *scene.cached):
            assert _shown_at(handle, time_code) == pytest.approx(translation(MOVER, time_code))
        undo.redo()
        assert (_generation().time_code, _generation().cached_time_codes) == (scene.synchronized_again, ())
        assert _shown_at(handle, scene.cached[-1]) == pytest.approx(translation(MOVER, scene.synchronized_again))


@pytest.fixture
def pushing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Push undo steps as Blender with global undo on, outside background mode, would (test_undo.py)."""
    undo.require_global_undo()
    monkeypatch.setattr(api, "_pushes_undo", lambda: True)
