"""Removals that fail for chosen datablocks, for the operations that share datablock_removal.remove_unused.

Each failure is injected by patching the removal module's one call into Blender, so src/ has no hooks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from proscenium_sync.synchronization import datablock_removal

if TYPE_CHECKING:
    from collections.abc import Sequence, Set

    import bpy
    import pytest


def fail_removing(monkeypatch: pytest.MonkeyPatch, failing: Set[bpy.types.ID]) -> None:
    """Make removing one of failing fail, or a call with one; by datablock, as an object and its mesh share a name."""
    remove = datablock_removal._batch_remove  # noqa: SLF001 - the module's one call into Blender

    def failing_remove(datablocks: Sequence[bpy.types.ID]) -> None:
        if any(d in failing for d in datablocks):
            raise RuntimeError("injected failure")
        remove(datablocks)

    monkeypatch.setattr(datablock_removal, "_batch_remove", failing_remove)
