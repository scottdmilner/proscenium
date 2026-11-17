"""A binding's display, kept between interaction calls while what built it is unchanged (bindings/shown_displays.py).

On F-NESTED-SELECTION. Builds are counted by wrapping the display component's correspondence builder; each check's
answer comes from the fixture, so a kept display that should have been rebuilt gives a wrong one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
from pxr import Usd, UsdGeom

from fixtures import interaction, time_variations
from proscenium_sync.interaction import display_correspondence
from proscenium_sync.results import ResultState
from support import undo

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import pytest

    from proscenium_sync.bindings import BindingHandle, Bindings

CRATE_B_BODY = "/World/Shelf/CrateB/Body"


def _builds(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """A list that grows by one at each correspondence build."""
    builds: list[int] = []
    build = display_correspondence.correspondence

    def counted(*args: object) -> object:
        builds.append(1)
        return build(*args)  # ty: ignore[invalid-argument-type]

    monkeypatch.setattr(display_correspondence, "correspondence", counted)
    return builds


def _synchronized(bindings: Bindings, tmp_path: Path) -> Iterator[tuple[BindingHandle, interaction.InteractionScene]]:
    with interaction.nested_selection(tmp_path) as scene:
        handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
        assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        yield handle, scene


def _highlighted(handle: BindingHandle) -> set[str]:
    """The source paths of the display's objects the whole world highlights, its viewport elements."""
    paths = set()
    for obj in handle.highlight_targets(["/World"]):
        picked = handle.resolve_pick(obj, obj.matrix_world)
        assert picked is not None
        paths.add(picked.source_path)
    return paths


def _crate_b_body(handle: BindingHandle) -> bpy.types.Object:
    """The display's object for CrateB's Body."""
    for obj in handle.highlight_targets(["/World"]):
        picked = handle.resolve_pick(obj, obj.matrix_world)
        if picked is not None and picked.source_path == CRATE_B_BODY:
            return obj
    raise AssertionError("no object shows CrateB's Body")


def test_calls_reuse_the_display_while_it_holds(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Calls build the correspondence once while nothing it was built from changes. An object hidden by hand rebuilds
    # it, and the hidden copy is no viewport element; shown again, it rebuilds once more and is one again.
    builds = _builds(monkeypatch)
    for handle, scene in _synchronized(bindings, tmp_path):
        assert _highlighted(handle) == scene.elements[0.0]
        assert handle.displayed(["/World"]) == [True]
        assert len(builds) == 1
        body = _crate_b_body(handle)  # noqa: E501
        body.hide_viewport = True
        assert _highlighted(handle) == scene.elements[0.0] - {CRATE_B_BODY}
        assert len(builds) == 2
        body.hide_viewport = False
        assert _highlighted(handle) == scene.elements[0.0]
        assert len(builds) == 3


def test_a_removed_object_rebuilds_the_display(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An object removed by hand is no longer named by the manifest's entries the display reads, so the next call
    # rebuilds it without that element rather than reading the removed object.
    builds = _builds(monkeypatch)
    for handle, scene in _synchronized(bindings, tmp_path):
        assert _highlighted(handle) == scene.elements[0.0]
        body = _crate_b_body(handle)  # noqa: E501
        bpy.data.objects.remove(body)
        assert _highlighted(handle) == scene.elements[0.0] - {CRATE_B_BODY}
        assert len(builds) == 2


def test_a_source_change_or_a_synchronization_rebuilds_the_display(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An edit to the live stage advances the source revision, so instance contexts derived on it follow; a
    # synchronization publishes another generation. Each rebuilds the display once.
    builds = _builds(monkeypatch)
    for handle, scene in _synchronized(bindings, tmp_path):
        handle.displayed(["/World"])
        stage = scene.stage
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            UsdGeom.Imageable(stage.GetPrimAtPath("/World/Bolt")).MakeInvisible()
        handle.displayed(["/World"])
        handle.displayed(["/World"])
        assert len(builds) == 2
        assert handle.synchronize(0.0).state is not ResultState.FATAL_FAILURE
        builds.clear()
        assert "/World/Bolt/Head" not in _highlighted(handle)
        assert len(builds) == 1


def test_nothing_is_kept_without_a_held_plan(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Once no plan is held for the generation shown, as after an undo past the held plans, the kept display is
    # rebuilt, and each call after builds it, its instance contexts from the live stage.
    builds = _builds(monkeypatch)
    for handle, scene in _synchronized(bindings, tmp_path):
        handle.displayed(["/World"])
        bindings.published_plans.clear()
        handle.displayed(["/World"])
        assert len(builds) == 2
        handle.displayed(["/World"])
        assert len(builds) == 3
        assert _highlighted(handle) == scene.elements[0.0]


def test_clearing_rebuilds_and_a_release_reports_no_stage(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # After the display is cleared, as proscenium.addon does after an undo, a redo, or a load, the next call builds it;
    # released, the binding has no live stage, which each call reports rather than answering from what was kept.
    import pytest

    from proscenium_sync.bindings import SourceUnavailableError

    builds = _builds(monkeypatch)
    for handle, _ in _synchronized(bindings, tmp_path):
        handle.displayed(["/World"])
        bindings.clear_shown_displays()
        handle.displayed(["/World"])
        assert len(builds) == 2
        handle.release()
        with pytest.raises(SourceUnavailableError):
            handle.displayed(["/World"])


def test_an_undo_rebuilds_the_display(bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # proscenium.addon clears the displays after an undo and a redo, which may free or restore the objects they name:
    # an undo that restores an object removed by hand restores its element, though the generation, the held plan, and
    # the source revision are as they were.
    undo.require_global_undo()
    builds = _builds(monkeypatch)
    for handle, scene in _synchronized(bindings, tmp_path):
        undo.push("synchronized")
        body = _crate_b_body(handle)
        bpy.data.objects.remove(body)
        undo.push("removed")
        assert _highlighted(handle) == scene.elements[0.0] - {CRATE_B_BODY}
        undo.undo()
        assert _highlighted(handle) == scene.elements[0.0]
        assert len(builds) == 3


def test_a_cache_call_rebuilds_the_display(bindings: Bindings, tmp_path: Path) -> None:
    # A cache call keeps the generation's held plan, whose key leaves out cached time codes, but changes its record, so
    # the copies it built join the display: at the frame showing 15, Scatter's highlight covers its third point.
    target = bpy.data.scenes["Scene"]
    third = f"{time_variations.SCATTER}/__index_2/Pebble"
    with time_variations.time_variations(tmp_path) as scene:
        handle = bindings.create_binding(target, name="Shot")
        assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
        assert handle.synchronize(scene.synchronized).state is not ResultState.FATAL_FAILURE
        handle.displayed([time_variations.SCATTER])
        [call] = scene.cache_groupings[0]
        assert handle.cache(call).state is not ResultState.FATAL_FAILURE
        target.frame_set(15)
        picked = {
            entity.source_path
            for obj in handle.highlight_targets([time_variations.SCATTER])
            if (entity := handle.resolve_pick(obj, obj.matrix_world)) is not None
        }
        assert third in picked
