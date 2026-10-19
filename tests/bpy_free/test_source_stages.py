"""A binding's source stage and evaluation stage (SRC-01, SRC-05).

Rules that hold for every binding run over each kind of source (bindings.KINDS); the rest are
about one kind: opening outside stage caches, for a file source.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Usd, UsdUtils

from fixtures import source_access
from fixtures.scenes import Scene, copy_scene
from fixtures.source_access import DISK, caller_settings, read_values
from proscenium.core.source_access import BindingSource, FileSource, SourceUnavailable
from support.usd import open_fresh

from .bindings import KINDS, binding

if TYPE_CHECKING:
    from pathlib import Path

UNLOADED = {"payA": None, "payB": None}


def _scene(tmp_path: Path) -> tuple[Path, Usd.Stage]:
    """A copy of the source-access scene and a caller's stage over it, which an attached binding uses."""
    root = copy_scene(Scene.SOURCE_ACCESS, tmp_path) / "root.usda"
    return root, open_fresh(root)


def _set_root_value_in_session(stage: Usd.Stage, value: float) -> None:
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        stage.GetPrimAtPath("/World").GetAttribute("rootValue").Set(value)


# --- every binding ------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_evaluation_stage_is_kept_and_reused(kind: str, tmp_path: Path) -> None:
    root, caller = _scene(tmp_path)
    source = binding(kind, root, caller)
    assert source.evaluation_stage is None
    stage = source.acquire()
    assert source.evaluation_stage == stage
    assert source.acquire() == stage


@pytest.mark.parametrize("kind", KINDS)
def test_live_stage_is_the_source_stage(kind: str, tmp_path: Path) -> None:
    # For a file source, the stage the binding opened, which it also evaluates; for an attached source, the
    # caller's stage, not the evaluation stage (ICON-07).
    root, caller = _scene(tmp_path)
    source = binding(kind, root, caller)
    stage = source.acquire()
    assert source.live_stage == (stage if kind == "file" else caller)
    assert (source.live_stage == stage) == (kind == "file")


@pytest.mark.parametrize("kind", KINDS)
def test_session_layer_opinions_are_displayed(kind: str, tmp_path: Path) -> None:
    # SRC-05: opinions in the source stage's session layer compose over the source.
    root, caller = _scene(tmp_path)
    source = binding(kind, root, caller)
    source.acquire()
    live = source.live_stage
    assert live is not None
    _set_root_value_in_session(live, 4.0)
    assert read_values(source.acquire()) == DISK | {"root": 4.0}


@pytest.mark.parametrize("kind", KINDS)
def test_unavailable_source(kind: str, tmp_path: Path) -> None:
    # A file that won't open.
    assert kind == "file"
    source = BindingSource(FileSource(tmp_path / "missing.usda"), Usd.Stage.LoadAll)
    with pytest.raises(SourceUnavailable):
        source.acquire()
    assert source.evaluation_stage is None
    assert source.live_stage is None


@pytest.mark.parametrize("kind", KINDS)
def test_payload_policy_sets_the_initial_load(kind: str, tmp_path: Path) -> None:
    root, caller = _scene(tmp_path)
    assert read_values(binding(kind, root, caller).acquire()) == DISK
    assert read_values(binding(kind, root, caller, Usd.Stage.LoadNone).acquire()) == DISK | UNLOADED


@pytest.mark.parametrize("kind", KINDS)
def test_payload_policy_change_applies_at_the_next_acquisition(kind: str, tmp_path: Path) -> None:
    root, caller = _scene(tmp_path)
    source = binding(kind, root, caller)
    stage = source.acquire()
    source.payload_policy = Usd.Stage.LoadNone
    assert read_values(stage) == DISK  # recorded, not applied
    assert source.acquire() == stage  # the same stage, its payloads unloaded
    assert read_values(stage) == DISK | UNLOADED
    source.payload_policy = Usd.Stage.LoadAll
    assert source.acquire() == stage
    assert read_values(stage) == DISK
    assert read_values(caller) == DISK  # an attached caller's load set is its own


@pytest.mark.parametrize("kind", KINDS)
def test_switching_payload_policy_and_back_keeps_the_display(kind: str, tmp_path: Path) -> None:
    # Metamorphic: load-all, then load-none again, composes what the binding showed before,
    # session-layer opinions included, and changes no layer.
    root, caller = _scene(tmp_path)
    source = binding(kind, root, caller, Usd.Stage.LoadNone)
    stage = source.acquire()
    live = source.live_stage
    assert live is not None
    _set_root_value_in_session(live, 4.0)
    before = read_values(source.acquire())
    for policy in (Usd.Stage.LoadAll, Usd.Stage.LoadNone):
        source.payload_policy = policy
        source.acquire()
    assert read_values(stage) == before
    assert not [layer.identifier for layer in stage.GetUsedLayers() if layer.dirty and not layer.anonymous]


# --- file sources: the binding's own source stage -----------------------------------------------


def test_ambient_cache(tmp_path: Path) -> None:
    # F-CACHED-STAGE "ambient-cache" (SRC-01): the source stage is not the cached ambient stage and is never
    # cached, and the ambient stage's session-layer opinions aren't composed (SRC-05).
    with source_access.cached_stage(tmp_path) as scene:
        ambient_settings = caller_settings(scene.ambient)
        stage = BindingSource(FileSource(scene.root), Usd.Stage.LoadAll).acquire()
        assert stage != scene.ambient
        assert not UsdUtils.StageCache.Get().Contains(stage)
        assert read_values(stage) == scene.disk_values
        assert read_values(scene.ambient) == scene.ambient_values
        assert caller_settings(scene.ambient) == ambient_settings


def test_bindings_on_one_file_have_their_own_stages(tmp_path: Path) -> None:
    root, caller = _scene(tmp_path)
    first, second = binding("file", root, caller).acquire(), binding("file", root, caller).acquire()
    assert first != second
    assert first.GetSessionLayer() != second.GetSessionLayer()
