"""Mirroring a scene's source selection again: as content becomes selectable, into another view layer, and per frame.

DECISIONS.md "Headless interaction functions": Blender deselects an unselectable collection's objects and an object a
hide flag hides, without selecting them again, so api/ mirrors the stored selection again when managed content becomes
selectable (ICON-41), when a window shows a view layer (ICON-39), and on a frame change for a scene whose selection has
entries of a binding that caches time codes. A window's view layer can't change without a window, so the message-bus
callback isn't run here; these tests call what it calls, and the window's part is tried by hand (Phase F).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from fixtures import interaction, time_variations
from proscenium.api.bindings import PersistentSelection, SelectionEntry
from proscenium.binding.results import ResultState

if TYPE_CHECKING:
    from pathlib import Path

    from pxr import Usd

    from proscenium.api.bindings import BindingHandle, Bindings

CHAIR = "/World/Props/Chair"
CHAIR_PARTS = {f"{CHAIR}/Geom/Seat", f"{CHAIR}/Geom/Back", f"{CHAIR}/Legs"}


def _scene() -> bpy.types.Scene:
    return bpy.data.scenes["Scene"]


def _synchronized(bindings: Bindings, stage: Usd.Stage) -> BindingHandle:
    handle = bindings.create_binding(_scene(), name="Shot")
    assert handle.attach(stage).state is not ResultState.FATAL_FAILURE
    assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
    return handle


def _selected(
    handle: BindingHandle, view_layer: bpy.types.ViewLayer | None = None
) -> list[tuple[str, bpy.types.Object]]:
    """The display's objects selected in the view layer, by source path."""
    layer = view_layer or _scene().view_layers[0]
    return [
        (picked.source_path, obj)
        for obj in bpy.data.collections["Shot"].all_objects
        if obj.select_get(view_layer=layer) and (picked := handle.resolve_pick(obj, obj.matrix_world)) is not None
    ]


def _select(bindings: Bindings, handle: BindingHandle, *paths: str) -> PersistentSelection:
    selection = PersistentSelection(tuple(SelectionEntry(handle.binding_id, p) for p in paths), None)
    bindings.set_source_selection(_scene(), selection)
    return selection


def test_selectable_again_mirrors_the_selection_back(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-41 on F-KIND-HIERARCHY: made unselectable, the destination's hide_select is set and Blender deselects its
    # objects, with the stored selection unchanged; made selectable, the selection is mirrored back.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        selection = _select(bindings, handle, CHAIR)
        assert {path for path, _ in _selected(handle)} == CHAIR_PARTS
        bindings.set_managed_selectable(_scene(), False)
        assert bpy.data.collections["Shot"].hide_select
        assert not bindings.managed_selectable(_scene())
        assert not _selected(handle)
        assert bindings.source_selection(_scene()) == selection
        bindings.set_managed_selectable(_scene(), True)
        assert bindings.managed_selectable(_scene())
        assert {path for path, _ in _selected(handle)} == CHAIR_PARTS


def test_another_view_layer_shown_is_mirrored_into(bindings: Bindings, tmp_path: Path) -> None:
    # ICON-39 on F-KIND-HIERARCHY with two view layers: setting the selection mirrors it into the active one only;
    # mirroring into the other, as a window showing it does, selects it there; unmanaged objects keep their selection
    # in both.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        other = _scene().view_layers.new("Other")
        unmanaged = bpy.data.objects.new("Unmanaged", None)
        _scene().collection.objects.link(unmanaged)
        for layer in _scene().view_layers:
            unmanaged.select_set(True, view_layer=layer)
        _select(bindings, handle, CHAIR)
        assert {path for path, _ in _selected(handle)} == CHAIR_PARTS
        assert not _selected(handle, other)
        bindings.mirror_source_selection(_scene(), other)
        assert {path for path, _ in _selected(handle, other)} == CHAIR_PARTS
        assert all(unmanaged.select_get(view_layer=layer) for layer in _scene().view_layers)


def test_each_frame_shows_the_selection(bindings: Bindings, tmp_path: Path) -> None:
    # On F-TIME-VARIATIONS, cached: Flicker and Scatter selected, each frame selects the objects it shows, Flicker's
    # marker at 0 and its box at 15, and Scatter's third point at 15 only, back and forth.
    third = f"{time_variations.SCATTER}/__index_2/Pebble"
    with time_variations.time_variations(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        [call] = scene.cache_groupings[0]
        assert handle.cache(call).state is not ResultState.FATAL_FAILURE
        _select(bindings, handle, time_variations.FLICKER, time_variations.SCATTER)
        for frame in (15, 0, 15, 0):
            _scene().frame_set(frame)
            selected = _selected(handle)
            flicker = [obj for path, obj in selected if path == time_variations.FLICKER]
            assert len(flicker) == 1 and not flicker[0].hide_viewport, frame
            assert (third in {path for path, _ in selected}) is (frame == 15), frame


def test_frames_mirror_nothing_without_cached_time_codes(bindings: Bindings, tmp_path: Path) -> None:
    # A display caching no time code changes no hide flag with the frame, so a frame change mirrors nothing: an object
    # deselected by hand stays deselected.
    with interaction.kind_hierarchy(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        _select(bindings, handle, CHAIR)
        seat = next(obj for path, obj in _selected(handle) if path == f"{CHAIR}/Geom/Seat")
        seat.select_set(False)
        _scene().frame_set(5)
        assert f"{CHAIR}/Geom/Seat" not in {path for path, _ in _selected(handle)}


def test_frames_mirror_nothing_while_an_operation_runs(bindings: Bindings, tmp_path: Path) -> None:
    # While a synchronization, cache call, or cleanup retry runs, a frame change mirrors nothing, cached or not.
    with time_variations.time_variations(tmp_path) as scene:
        handle = _synchronized(bindings, scene.stage)
        [call] = scene.cache_groupings[0]
        assert handle.cache(call).state is not ResultState.FATAL_FAILURE
        _select(bindings, handle, time_variations.MOVER)
        [(_, mover)] = _selected(handle)
        mover.select_set(False)
        bindings.running = True
        try:
            _scene().frame_set(5)
        finally:
            bindings.running = False
        assert not _selected(handle)
