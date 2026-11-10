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
is it halved, each half removed the same way, until each datablock that fails is alone: a few failures among n take
about log n calls each, where one call per datablock would take n. A datablock is never passed to Blender once removed,
since Blender crashes on one; a failed call may have removed some.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import bpy

from ..binding.persistence import id_property_records

if TYPE_CHECKING:
    from collections.abc import Collection, Hashable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class RemovalOutcome[K: Hashable]:
    """What remove_unused did with each datablock, by the caller's key for it."""

    removed_keys: set[K] = field(default_factory=set)  # removed, or already gone
    released_keys: set[K] = field(default_factory=set)  # left intact: something else uses it
    pending_reasons_by_key: dict[K, str] = field(default_factory=dict)  # left as it was, with why


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
        if datablock is None or not id_property_records.alive(datablock):
            outcome.removed_keys.add(key)
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
        before = len(undecided)
        level = _classify_and_collect_removable(undecided, users, key_of, outcome)
        undecided -= outcome.released_keys | outcome.pending_reasons_by_key.keys() | set(level)
        if len(undecided) == before:  # nothing decided: what's left uses each other
            break
        failures = remove_datablocks_collecting_failures([present[key] for key in level])
        for index, key in enumerate(level):
            if (error := failures.get(index)) is not None:
                outcome.pending_reasons_by_key[key] = str(error)
            else:
                outcome.removed_keys.add(key)
    for key in undecided:  # only datablocks using each other in a cycle are left
        outcome.pending_reasons_by_key[key] = "it and the resources using it use each other"
    return outcome


def _classify_and_collect_removable[K: Hashable](
    undecided: Collection[K], users: Mapping[K, set[int]], key_of: Mapping[int, K], outcome: RemovalOutcome[K]
) -> list[K]:
    """Release or leave pending each of undecided that is decided now; the keys whose users are all removed."""
    level: list[K] = []
    for key in sorted(undecided, key=str):
        using = {key_of.get(uid) for uid in users[key]}
        if None in using or using & outcome.released_keys:  # something besides the others uses it
            outcome.released_keys.add(key)
        elif using & outcome.pending_reasons_by_key.keys():
            outcome.pending_reasons_by_key[key] = "a resource using it couldn't be removed"
        elif using <= outcome.removed_keys:
            level.append(key)
    return level


def remove_datablocks_collecting_failures(datablocks: Sequence[bpy.types.ID]) -> dict[int, Exception]:
    """Attempt removal of live datablocks and return failures by their input indices."""
    failures: dict[int, Exception] = {}
    if datablocks:
        _remove_halving(list(enumerate(datablocks)), failures)
    return failures


def _remove_halving(indexed: list[tuple[int, bpy.types.ID]], failures: dict[int, Exception]) -> None:
    """Remove indexed's datablocks, each alive, in one call; if it raises, each half of those left the same way."""
    try:
        _batch_remove([datablock for _, datablock in indexed])
    except Exception as error:  # noqa: BLE001 - a failure is reported, never raised
        if len(indexed) == 1:
            failures[indexed[0][0]] = error
            return
        left = [(index, d) for index, d in indexed if id_property_records.alive(d)]  # removed by the failed call
        half = len(left) // 2
        for part in (left[:half], left[half:]):
            if part:
                _remove_halving(part, failures)


def _batch_remove(datablocks: Sequence[bpy.types.ID]) -> None:
    """Remove datablocks in one call."""
    bpy.data.batch_remove(datablocks)
