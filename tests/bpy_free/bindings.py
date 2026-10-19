"""Bindings with each kind of source, so source-access tests can run over all of them (source-access.md)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pxr import Usd

from proscenium.core.source_access import BindingSource, FileSource

if TYPE_CHECKING:
    from pathlib import Path

KINDS = ("file",)


def binding(
    kind: str, root: Path, caller: Usd.Stage, payload_policy: Usd.Stage.InitialLoadSet = Usd.Stage.LoadAll
) -> BindingSource:
    """A binding on root, with its own source stage for "file". caller is the stage an attached source would use."""
    assert kind == "file", kind
    return BindingSource(FileSource(root), payload_policy)
