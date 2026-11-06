"""Removing datablocks, in one call where none fails (pipeline.md#synchronization-transaction).

Each call of bpy.data.batch_remove scans the file, so removing datablocks one call each costs their number times the
file's size. remove makes one call, and only when it raises removes the rest one call each, to find which fail. A
datablock is never passed to Blender once removed, since Blender crashes on one; a failed call may have removed some.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from ..binding.runtime import state

if TYPE_CHECKING:
    from collections.abc import Sequence


def remove(datablocks: Sequence[bpy.types.ID]) -> dict[int, Exception]:
    """Remove datablocks, each alive; why each that couldn't be removed wasn't, by its index in datablocks."""
    if not datablocks:
        return {}
    try:
        _batch_remove(datablocks)
    except Exception:  # noqa: BLE001 - which failed is found one at a time below
        pass
    else:
        return {}
    failures: dict[int, Exception] = {}
    for index, datablock in enumerate(datablocks):
        if not state.alive(datablock):  # removed by the failed call
            continue
        try:
            _batch_remove([datablock])
        except Exception as error:  # noqa: BLE001 - a failure is reported, never raised
            failures[index] = error
    return failures


def _batch_remove(datablocks: Sequence[bpy.types.ID]) -> None:
    """Remove datablocks in one call."""
    bpy.data.batch_remove(datablocks)
