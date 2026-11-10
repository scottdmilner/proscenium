"""Synchronizations whose steps fail as the transaction fixtures say (fixtures/transaction.py).

Each failure is injected by patching the step's module function for one synchronization alone, so src/ has no hooks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from fixtures import transaction
from proscenium.synchronization import application, datablock_removal, preparation_resources

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
    held: list[tuple[RepresentationRole, bpy.types.ID]] = []
    failing: set[bpy.types.ID] = set()
    hold, world, remove = (
        preparation_resources.PreparationResources.track,
        application._matrix_from_buffer,
        datablock_removal._batch_remove,
    )  # noqa: SLF001
    worlds: list[object] = []

    def recording(
        work: preparation_resources.PreparationResources, entry_key: str, role: RepresentationRole, d: bpy.types.ID
    ) -> None:
        held.append((role, d))
        hold(work, entry_key, role, d)

    def failing_world(buffer: memoryview, copy: int) -> Any:  # called once a copy's resources are made
        worlds.append(copy)
        if len(worlds) * len(transaction.ROLES_PER_PLACEHOLDER) == scene.prepared_before_failure:
            raise RuntimeError("injected preparation failure")
        return world(buffer, copy)

    def failing_remove(datablocks: Sequence[bpy.types.ID]) -> None:
        failing.update(next(d for r, d in held if r == role) for role in scene.failed_disposals)
        if any(d in failing for d in datablocks):  # so a call removing one fails, the batch's included
            raise RuntimeError("injected disposal failure")
        remove(datablocks)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(preparation_resources.PreparationResources, "track", recording)
        patch.setattr(application, "_matrix_from_buffer", failing_world)
        patch.setattr(datablock_removal, "_batch_remove", failing_remove)
        result = handle.synchronize(time_code)
    assert len(held) == scene.prepared_before_failure
    return result, failing
