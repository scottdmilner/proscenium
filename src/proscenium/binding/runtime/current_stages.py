"""Every binding's stages, kept consistent with the bindings that exist (source-access.md#source-stages).

The stages are source access's StageRegistry, created unattached on first use by binding identity. Whenever the
bindings' state was rebuilt since (state.rebuild_count), the next use drops evaluation stages of bindings that are gone,
keeping their attachments for undo and redo (StageRegistry.prune).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..source_access import StageRegistry
from . import binding_configs, state

if TYPE_CHECKING:
    from ..source_access import BindingStages
    from ..source_access.binding_ids import BindingId


class CurrentStages:
    """Every binding's stages, compared with the bindings before each use if their state was rebuilt since."""

    _registry: StageRegistry
    _pruned_at: int | None  # state.rebuild_count() when the stages were last compared with the bindings

    def __init__(self) -> None:
        self._registry = StageRegistry()
        self._pruned_at = None

    def attached(self, binding_id: BindingId) -> BindingStages:
        """The binding's stages on an attached source (StageRegistry.attached)."""
        return self._current().attached(binding_id)

    def get(self, binding_id: BindingId) -> BindingStages | None:
        """The binding's stages, or None before their first use."""
        return self._current().get(binding_id)

    def release(self, binding_id: BindingId) -> None:
        """Release one binding without reading its records (StageRegistry.release)."""
        self._registry.release(binding_id)

    def prune(self) -> None:
        """Drop evaluation stages of bindings that no longer exist (StageRegistry.prune).

        With no stages, as before a session's first synchronization, it reads no configurations, so calling it
        (as the undo and redo handler does) never rebuilds the bindings' state.
        """
        if self._registry:
            found = binding_configs.find_bindings()
            self._registry.prune({f.binding_id for f in found})
        self._pruned_at = state.rebuild_count()

    def clear(self) -> None:
        """Drop every binding's stages, leaving each binding with no source stage or attachment."""
        self._registry = StageRegistry()
        self._pruned_at = None

    def _current(self) -> StageRegistry:
        """The stages, pruned first if the bindings' state was rebuilt since they were last compared with it."""
        if self._pruned_at != state.rebuild_count():
            self.prune()
        return self._registry
