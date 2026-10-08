"""The reset between blender-layer tests: leftovers are detected, and reset plus cleanup remove them.

Each test dirties state on purpose, checks that baseline_problems() reports it,
then resets as the conftest would and checks the state is clean again.
"""

from __future__ import annotations

import gc
from typing import TYPE_CHECKING

import bpy
import pytest
from pxr import Sdf, Usd, UsdUtils

import proscenium

from . import state as blender_state

if TYPE_CHECKING:
    from collections import Counter
    from pathlib import Path


def _reset_and_check(baseline_handlers: dict[str, Counter[str]], before: blender_state.HandlerLists) -> list[str]:
    blender_state.cleanup(before)
    blender_state.reset()
    return blender_state.baseline_problems(baseline_handlers)


def test_leftover_data_is_reported_and_reset(baseline_handlers: dict[str, Counter[str]]) -> None:
    before = blender_state.snapshot_handlers()
    scene = bpy.context.scene
    assert scene is not None
    scene.collection.objects.link(bpy.data.objects.new("Leftover", None))
    problems = blender_state.baseline_problems(baseline_handlers)
    assert any("bpy.data.objects" in p for p in problems)
    assert any("one empty scene" in p for p in problems)
    assert _reset_and_check(baseline_handlers, before) == []


def test_leftover_handler_is_reported_and_removed(baseline_handlers: dict[str, Counter[str]]) -> None:
    before = blender_state.snapshot_handlers()

    @bpy.app.handlers.persistent  # survives the factory reset, so only cleanup removes it
    def leftover(*_args: object) -> None:
        pass

    bpy.app.handlers.load_post.append(leftover)
    blender_state.reset()
    assert any("leftover" in p for p in blender_state.baseline_problems(baseline_handlers))
    assert _reset_and_check(baseline_handlers, before) == []


def test_registered_extension_is_reported_and_unregistered(baseline_handlers: dict[str, Counter[str]]) -> None:
    before = blender_state.snapshot_handlers()
    proscenium.register()
    assert "the extension is still registered" in blender_state.baseline_problems(baseline_handlers)
    assert _reset_and_check(baseline_handlers, before) == []


def test_cached_stage_is_reported_and_cleared(baseline_handlers: dict[str, Counter[str]]) -> None:
    before = blender_state.snapshot_handlers()
    UsdUtils.StageCache.Get().Insert(Usd.Stage.CreateInMemory())
    assert "UsdUtils.StageCache is not empty" in blender_state.baseline_problems(baseline_handlers)
    assert _reset_and_check(baseline_handlers, before) == []


def test_dirty_layer_held_past_the_test_is_reported(baseline_handlers: dict[str, Counter[str]], tmp_path: Path) -> None:
    layer = Sdf.Layer.CreateNew(str(tmp_path / "held.usda"))
    Sdf.CreatePrimInLayer(layer, "/Unsaved")
    assert any("unsaved edits" in p for p in blender_state.baseline_problems(baseline_handlers))
    del layer
    gc.collect()
    assert not any("unsaved edits" in p for p in blender_state.baseline_problems(baseline_handlers))


@pytest.mark.parametrize("attempt", [1, 2])
def test_state_does_not_carry_between_tests(attempt: int) -> None:
    # Both runs see a clean start (checked by the autouse fixture) despite the first one dirtying it.
    assert "Carried" not in bpy.data.objects
    bpy.data.objects.new("Carried", None)
