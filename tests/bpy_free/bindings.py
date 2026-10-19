"""Bindings with either kind of source, so source-access tests can run over both (source-access.md#source-stages).

An attached source holds only a weak reference to the caller's stage, so the test keeps that
stage alive; a file source ignores it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pxr import Usd

from proscenium.core.source_access import AttachedSource, BindingSource, FileSource

if TYPE_CHECKING:
    from pathlib import Path

KINDS = ("file", "attached")


def binding(
    kind: str, root: Path, caller: Usd.Stage, payload_policy: Usd.Stage.InitialLoadSet = Usd.Stage.LoadAll
) -> BindingSource:
    """A binding on root: its own source stage for "file", caller's stage attached for "attached"."""
    if kind == "file":
        return BindingSource(FileSource(root), payload_policy)
    source = AttachedSource("shot")
    source.attach(caller)
    return BindingSource(source, payload_policy)
