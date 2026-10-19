"""Every binding's source stage, and attaching callers' stages under source keys (SID-03 to SID-06, ICON-07)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Usd

from fixtures import source_access
from fixtures.source_access import read_values
from proscenium.core.source_access import AttachedSource, AttachResult, FileSource, SourceRegistry

if TYPE_CHECKING:
    from pathlib import Path


def _registry(*bindings: tuple[str, str]) -> SourceRegistry:
    """A registry with an unattached load-all binding per (binding_id, key) of an attached source."""
    registry = SourceRegistry()
    for binding_id, key in bindings:
        registry.add_attached(binding_id, key, Usd.Stage.LoadAll)
    return registry


def _attached(registry: SourceRegistry, binding_id: str) -> AttachedSource:
    source = registry.get(binding_id).source
    assert isinstance(source, AttachedSource)
    return source


def _attached_stage(registry: SourceRegistry, binding_id: str) -> Usd.Stage | None:
    return _attached(registry, binding_id).stage


def test_a_key_attaches_every_binding_with_it(tmp_path: Path) -> None:
    # SID-03: two bindings share a key; a third has another.
    with source_access.reattach(tmp_path) as scene:
        registry = _registry(("a", "shot"), ("b", "shot"), ("c", "other"))
        result = registry.attach("shot", scene.caller)
        assert result == AttachResult(attached=("a", "b"), unconfirmed=())
        assert [_attached_stage(registry, b) for b in "abc"] == [scene.caller, scene.caller, None]
        assert read_values(registry.get("a").acquire()) == scene.values


def test_reattachment_needs_an_exact_key(tmp_path: Path) -> None:
    # SID-04: case and whitespace count.
    with source_access.reattach(tmp_path) as scene:
        registry = _registry(("a", "shot"))
        for key in ("Shot", " shot", "shot "):
            assert registry.attach(key, scene.caller) == AttachResult(attached=(), unconfirmed=())
        assert _attached_stage(registry, "a") is None


def test_root_layer_never_finds_a_binding(tmp_path: Path) -> None:
    # SID-05: the stored root layer matches, the key doesn't.
    with source_access.reattach(tmp_path) as scene:
        registry = SourceRegistry()
        registry.add_attached("a", "shot", Usd.Stage.LoadAll, scene.caller.GetRootLayer().identifier)
        assert registry.attach("other", scene.caller).attached == ()
        assert _attached_stage(registry, "a") is None


def test_a_stage_over_the_same_root_layer_reattaches(tmp_path: Path) -> None:
    with source_access.reattach(tmp_path) as scene:
        registry = _registry(("a", "shot"))
        registry.attach("shot", scene.caller)
        assert registry.attach("shot", scene.same_root).attached == ("a",)
        assert _attached_stage(registry, "a") == scene.same_root


def test_a_different_root_layer_needs_confirmation(tmp_path: Path) -> None:
    # SID-06: without confirmation, nothing changes for any binding with the key; with it, the stored
    # identifier becomes the new stage's.
    with source_access.reattach(tmp_path) as scene:
        registry = _registry(("a", "shot"), ("b", "shot"))
        registry.attach("shot", scene.caller)
        registry.add_attached("c", "shot", Usd.Stage.LoadNone)  # unattached, no stored root layer
        refused = registry.attach("shot", scene.other_root)
        assert refused == AttachResult(attached=(), unconfirmed=("a", "b"))
        assert [_attached_stage(registry, b) for b in "abc"] == [scene.caller, scene.caller, None]
        assert _attached(registry, "a").root_layer_identifier == scene.caller.GetRootLayer().identifier
        confirmed = registry.attach("shot", scene.other_root, confirm=True)
        assert confirmed == AttachResult(attached=("a", "b", "c"), unconfirmed=())
        identifier = scene.other_root.GetRootLayer().identifier
        assert [_attached(registry, b).root_layer_identifier for b in "abc"] == [identifier] * 3
        assert [_attached_stage(registry, b) for b in "abc"] == [scene.other_root] * 3


def test_live_stage_is_the_attached_stage(tmp_path: Path) -> None:
    # ICON-07: the live stage is the caller's attached stage, not the evaluation stage.
    with source_access.reattach(tmp_path) as scene:
        registry = _registry(("a", "shot"))
        registry.attach("shot", scene.caller)
        source = registry.get("a")
        evaluation = source.acquire()
        assert source.live_stage == scene.caller
        assert evaluation != scene.caller


def test_every_binding_has_its_source_stage(tmp_path: Path) -> None:
    with source_access.reattach(tmp_path) as scene:
        registry = SourceRegistry()
        file_backed = registry.add_file("f", scene.root, Usd.Stage.LoadAll)
        attached = registry.add_attached("m", "shot", Usd.Stage.LoadAll)
        assert registry.get("f") is file_backed
        assert isinstance(file_backed.source, FileSource)
        assert registry.get("m") is attached
        registry.remove("f")
        with pytest.raises(KeyError):
            registry.get("f")


def test_attach_never_reaches_a_file_backed_binding(tmp_path: Path) -> None:
    # The file-backed binding opens the caller's root layer, so only the key could tell them apart.
    with source_access.reattach(tmp_path) as scene:
        registry = SourceRegistry()
        file_backed = registry.add_file("shot", scene.root, Usd.Stage.LoadAll)
        assert registry.attach("shot", scene.caller) == AttachResult(attached=(), unconfirmed=())
        assert file_backed.acquire() != scene.caller
        assert file_backed.live_stage == file_backed.evaluation_stage
