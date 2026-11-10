"""Caching time codes in the published generation, against the stub application layer (pipeline.md#cached-time-codes).

On F-CACHED-TIME-CODES and F-SOURCE-CHANGE (fixtures/transaction.py), M5 plan, E1 and E3. The stub keys each
placeholder's transform at each cached time code, so a frame shows the latest cached time code at or before it;
expected translations come from how the scene is built (transaction.translation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import bpy
import pytest
from pxr import Usd

from fixtures import transaction
from fixtures.transaction import translation
from proscenium.api import bindings as api
from proscenium.binding.persistence import binding_state, manifests, records
from proscenium.binding.persistence.manifests import RepresentationRole
from proscenium.binding.results import DiagnosticCode, ResultState
from proscenium.binding.runtime import ownership
from support import undo

if TYPE_CHECKING:
    from pathlib import Path

    from fixtures.transaction import CachedTimeCodesScene, SourceChangeScene
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
            before.settings,
            before.unit_scale,
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


def test_a_call_reads_the_manifest_once(bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Its update by entry starts from the manifest the call read, which reading again would cost as much (F3).
    with transaction.cached_time_codes(tmp_path) as scene:
        handle = _synchronized(bindings, scene)
        read = manifests.read_manifest
        reads: list[None] = []

        def counted(destination: bpy.types.Collection) -> Any:
            reads.append(None)
            return read(destination)

        monkeypatch.setattr(manifests, "read_manifest", counted)
        assert handle.cache(scene.cached).state is ResultState.SUCCESS
        assert len(reads) == 1


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
        undo.undo_unpushed()
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
    monkeypatch.setattr(api, "_undo_steps_enabled", lambda: True)


def _unchanged_by_cache(handle: BindingHandle, call: Any) -> Any:
    """Call's result, checking it cached nothing: the generation and manifest as before, and no action made."""
    before, entries = _generation(), _entries(handle)
    result = call()
    assert (_generation(), _entries(handle)) == (before, entries)
    assert not bpy.data.actions
    return result


def _edited(scene: SourceChangeScene, handle: BindingHandle) -> None:
    scene.edit()


def _reloaded(scene: SourceChangeScene, handle: BindingHandle) -> None:
    scene.rewrite_on_disk()
    assert handle.reload().state is ResultState.SUCCESS


def _attached_again(scene: SourceChangeScene, handle: BindingHandle) -> None:
    assert handle.attach(scene.caller).state is ResultState.SUCCESS


@pytest.mark.parametrize("change", [_edited, _reloaded, _attached_again], ids=["edit", "reload", "attach"])
def test_after_a_source_change_cache_needs_a_synchronization(bindings: Bindings, tmp_path: Path, change: Any) -> None:
    # CACHE-05 on F-SOURCE-CHANGE "changed-before-cache": after an edit to sub.usda, a reload of its rewritten file, or
    # attaching the stage again, cache fails saying the binding needs synchronizing and caches nothing, its cached
    # time codes included; once synchronized again, the same call caches.
    with transaction.source_change(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        assert handle.attach(scene.caller).state is ResultState.SUCCESS
        assert handle.synchronize(0).state is ResultState.SUCCESS
        change(scene, handle)
        for time_codes in ([5, 10], [0]):
            result = _unchanged_by_cache(handle, lambda t=time_codes: handle.cache(t))
            assert [d.code for d in result.diagnostics] == [DiagnosticCode.NEEDS_SYNCHRONIZATION]
        assert handle.synchronize(0).state is ResultState.SUCCESS
        assert handle.cache([5, 10]).state is ResultState.SUCCESS


def test_without_a_source_change_the_same_call_caches(bindings: Bindings, tmp_path: Path) -> None:
    # CACHE-05's control on F-SOURCE-CHANGE: with no change, nor any after a call, cache keeps caching.
    with transaction.source_change(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        assert handle.attach(scene.caller).state is ResultState.SUCCESS
        assert handle.synchronize(0).state is ResultState.SUCCESS
        assert handle.cache([5]).state is ResultState.SUCCESS
        assert handle.cache([5, 10]).time_codes == (Usd.TimeCode(10),)


def test_a_binding_with_nothing_published_needs_a_synchronization(bindings: Bindings, tmp_path: Path) -> None:
    # Nothing to cache time codes in, so the call fails as after a source change, before reading the source.
    with transaction.cached_time_codes(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        result = handle.cache(scene.cached)
        assert [d.code for d in result.diagnostics] == [DiagnosticCode.NEEDS_SYNCHRONIZATION]
        assert binding_state.read_generation(bpy.data.collections["Shot"]) is None


def test_a_generation_at_the_default_time_code_has_nothing_to_cache(bindings: Bindings, tmp_path: Path) -> None:
    # CACHE-06 on F-CACHED-TIME-CODES "default-time-code": cache at any time codes caches nothing and succeeds.
    with transaction.cached_time_codes(tmp_path) as scene:
        handle = bindings.create_binding(_scene(), name="Shot")
        assert handle.attach(scene.caller).state is ResultState.SUCCESS
        assert handle.synchronize(Usd.TimeCode.Default()).state is ResultState.SUCCESS
        result = _unchanged_by_cache(handle, lambda: handle.cache([*scene.cached, *scene.failing]))
        assert (result.state, result.time_codes) == (ResultState.SUCCESS, ())
        assert _generation().cached_time_codes == ()


def test_synchronizing_again_holds_only_its_own_time_code(bindings: Bindings, tmp_path: Path) -> None:
    # CACHE-07 on F-CACHED-TIME-CODES "synchronize-again": after caching, synchronizing at 10 gives a generation whose
    # only time code is 10, showing 10's values at every frame, and the cached time codes' actions are retired.
    with transaction.cached_time_codes(tmp_path) as scene:
        handle = _synchronized(bindings, scene)
        assert handle.cache(scene.cached).state is ResultState.SUCCESS
        assert handle.synchronize(scene.synchronized_again).state is ResultState.SUCCESS
        generation = _generation()
        assert (generation.time_code, generation.cached_time_codes) == (scene.synchronized_again, ())
        assert not bpy.data.actions
        assert {e.role for e in _entries(handle).values()} == set(transaction.ROLES_PER_PLACEHOLDER)
        for frame in (scene.synchronized, *scene.cached, *scene.failing):
            assert _shown_at(handle, frame) == pytest.approx(translation(MOVER, scene.synchronized_again))
