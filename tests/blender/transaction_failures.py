"""Synchronizations whose steps fail as the transaction fixtures say (fixtures/transaction.py).

Each failure is injected by patching the step's module function for one synchronization alone, so src/ has no hooks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from fixtures import transaction
from proscenium.synchronization import application, prepared_work, removal

if TYPE_CHECKING:
    from collections.abc import Sequence

    import bpy

    from fixtures.transaction import PreparationCleanupFailureScene
    from proscenium.api.bindings import BindingHandle
    from proscenium.binding.persistence.manifests import RepresentationRole
    from proscenium.binding.results import Result


def failing_preparation(
    handle: BindingHandle, scene: PreparationCleanupFailureScene, time_code: float
) -> tuple[Result, set[bpy.types.ID]]:
    """Synchronize with preparation and some of its disposal failing as the fixture says; the result and leftovers."""
    tracked: list[tuple[RepresentationRole, bpy.types.ID]] = []
    failing: set[bpy.types.ID] = set()
    track, world, remove = prepared_work.PreparedWork.track, application._world, removal._batch_remove  # noqa: SLF001
    worlds: list[object] = []

    def recording(work: prepared_work.PreparedWork, entry_key: str, role: RepresentationRole, d: bpy.types.ID) -> None:
        tracked.append((role, d))
        track(work, entry_key, role, d)

    def failing_world(matrix: Any) -> Any:  # called once a placeholder's resources are made
        worlds.append(matrix)
        if len(worlds) * len(transaction.ROLES_PER_PLACEHOLDER) == scene.prepared_before_failure:
            raise RuntimeError("injected preparation failure")
        return world(matrix)

    def failing_remove(datablocks: Sequence[bpy.types.ID]) -> None:
        failing.update(next(d for r, d in tracked if r == role) for role in scene.failed_disposals)
        if any(d in failing for d in datablocks):  # so a call removing one fails, the batch's included
            raise RuntimeError("injected disposal failure")
        remove(datablocks)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(prepared_work.PreparedWork, "track", recording)
        patch.setattr(application, "_world", failing_world)
        patch.setattr(removal, "_batch_remove", failing_remove)
        result = handle.synchronize(time_code)
    assert len(tracked) == scene.prepared_before_failure
    return result, failing
