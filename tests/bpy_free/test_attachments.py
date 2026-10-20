"""Every binding's source stage in the runtime registry, and the attached stage as the live stage (ICON-07).

The key contract reads the binding records, so its tests are in tests/blender/test_bindings.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Usd

from fixtures import source_access
from proscenium.core.source_access import AttachedSource, FileSource, SourceRegistry

if TYPE_CHECKING:
    from pathlib import Path


def test_live_stage_is_the_attached_stage(tmp_path: Path) -> None:
    # ICON-07: the live stage is the caller's attached stage, not the evaluation stage.
    with source_access.reattach(tmp_path) as scene:
        registry = SourceRegistry()
        source = registry.add_attached("a", "shot", Usd.Stage.LoadAll)
        assert isinstance(source.source, AttachedSource)
        source.source.attach(scene.caller)
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
        assert "f" in registry
        registry.remove("f")
        assert "f" not in registry
        with pytest.raises(KeyError):
            registry.get("f")
