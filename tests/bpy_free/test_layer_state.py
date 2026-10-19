"""Layers are displayed as loaded, and never reloaded by acquiring (LAYER-01), for each kind of source.

For an attached source, the dirty-layer fixture's caller is the attached stage; for a file source,
it is another tool's stage on the same files.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pxr import Sdf, Tf, Usd

from fixtures import source_access
from fixtures.source_access import read_values

from .bindings import KINDS, binding

if TYPE_CHECKING:
    from pathlib import Path


def _notices(*stages: Usd.Stage) -> tuple[list[object], list[Tf.Notice.Listener]]:
    """Change notices from the given stages, collected until the listeners are revoked."""
    notices: list[object] = []
    listeners = [
        Tf.Notice.Register(Usd.Notice.ObjectsChanged, lambda notice, _: notices.append(notice), stage)
        for stage in stages
    ]
    return notices, listeners


@pytest.mark.parametrize("kind", KINDS)
def test_layers_are_displayed_as_loaded(kind: str, tmp_path: Path) -> None:
    # F-DIRTY-LAYER "as-loaded" (LAYER-01): unsaved edits are composed, sub.usda keeps its loaded value though its
    # file was rewritten, and acquiring again reloads nothing.
    with source_access.dirty_layer(tmp_path) as scene:
        source = binding(kind, scene.root, scene.caller)
        stage = source.acquire()
        assert read_values(stage) == scene.in_process_values
        assert scene.disk_values["sub"] != scene.in_process_values["sub"]
        notices, listeners = _notices(stage, scene.caller)
        source.acquire()
        for listener in listeners:
            listener.Revoke()
        assert notices == []
        assert all(Sdf.Layer.Find(str(path)).dirty for path in scene.dirty_contributing.values())
