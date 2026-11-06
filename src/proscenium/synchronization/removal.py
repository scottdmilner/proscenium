"""Removing managed datablocks nothing else uses, users first (pipeline.md#synchronization-transaction).

Disposal of prepared work, retirement of obsolete resources, and a cleanup retry share remove_unused. It reads each
datablock's current users once, before removing anything (lifecycle.md#pending-cleanup, PEND-02), then decides each:

- One whose only users are the operation's own holders, which the caller names, and other datablocks it removes first
  is removed, a level at a time, users first.
- One anything else uses is left intact and released from management (lifecycle.md#ownership-and-lifecycle):
  unmanaged content, a manifest naming it, which makes the manifest's datablock a user, a fake user, or one of the
  datablocks itself released.
- One whose removal fails, or whose user's did, is left pending, with why.

Each call of bpy.data.batch_remove scans the file, so each level is removed in one call, and only when that raises
are its datablocks removed one call each, to find which fail. A datablock is never passed to Blender once removed,
since Blender crashes on one; a failed call may have removed some.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import bpy

from ..binding.runtime import state

if TYPE_CHECKING:
    from collections.abc import Collection, Hashable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class RemovalOutcome[K: Hashable]:
    """What remove_unused did with each datablock, by the caller's key for it."""

    removed: set[K] = field(default_factory=set)  # removed, or already gone
    released: set[K] = field(default_factory=set)  # left intact: something else uses it
    pending: dict[K, str] = field(default_factory=dict)  # left as it was, with why


def remove_unused[K: Hashable](
    datablocks: Mapping[K, bpy.types.ID | None], holders: Collection[bpy.types.ID] = ()
) -> RemovalOutcome[K]:
    """Remove each of datablocks that nothing but holders and the others removed first uses; what became of each.

    A datablock that is None or already removed counts as removed. holders are the operation's own users of the
    datablocks, such as a staging collection or the ledger's Text, which don't keep one from being removed.
    """
    outcome: RemovalOutcome[K] = RemovalOutcome()
    present: dict[K, bpy.types.ID] = {}
    for key, datablock in datablocks.items():
        if datablock is None or not state.alive(datablock):
            outcome.removed.add(key)
        else:
            present[key] = datablock
    if not present:
        return outcome
    key_of = {d.session_uid: key for key, d in present.items()}
    ignored = {h.session_uid for h in holders}
    user_map = bpy.data.user_map(subset=list(present.values()))
    users = {key: {u.session_uid for u in user_map[d]} - ignored for key, d in present.items()}
    undecided = set(present)
    while undecided:
        level: list[K] = []
        before = len(undecided)
        for key in sorted(undecided, key=str):
            using = {key_of.get(uid) for uid in users[key]}
            if None in using or using & outcome.released:  # something besides the others uses it
                outcome.released.add(key)
            elif using & outcome.pending.keys():
                outcome.pending[key] = "a resource using it couldn't be removed"
            elif using <= outcome.removed:
                level.append(key)
        undecided -= outcome.released | outcome.pending.keys() | set(level)
        if len(undecided) == before:  # nothing decided: what's left uses each other
            break
        failures = remove([present[key] for key in level])
        for index, key in enumerate(level):
            if (error := failures.get(index)) is not None:
                outcome.pending[key] = str(error)
            else:
                outcome.removed.add(key)
    for key in undecided:  # only datablocks using each other in a cycle are left
        outcome.pending[key] = "it and the resources using it use each other"
    return outcome


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
