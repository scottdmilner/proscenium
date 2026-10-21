"""Bindings with either kind of source, so source-access tests can run over both (source-access.md#source-stages).

An attached source holds the caller's stage; a file source ignores it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from proscenium.core.source_access import AttachedSource, BindingSource, FileSource, SourceKind

if TYPE_CHECKING:
    from pathlib import Path

    from pxr import Usd

KINDS = tuple(SourceKind)


def binding(kind: str, root: Path, caller: Usd.Stage) -> BindingSource:
    """A binding on root: its own source stage for a file source, caller's stage attached for an attached one."""
    if kind == SourceKind.FILE:
        return BindingSource(FileSource(root))
    source = AttachedSource("shot")
    source.attach(caller)
    return BindingSource(source)
