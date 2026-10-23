"""Every binding's stages, kept consistent with the bindings (source-access.md#source-stages).

The stages themselves are core's StageRegistry, made from each binding's configuration on first use. This keeps
them consistent with the bindings that exist: whenever the bindings' state was rebuilt (state.rebuild_count), as
after a load, undo, or redo, or when scenes are added or removed, the next use first drops the stages of bindings
that are gone or can't synchronize (StageRegistry.prune).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.source_access import StageRegistry
from ..persistence.binding_records import BindingConfig
from . import binding_configs, state

if TYPE_CHECKING:
    import os

    from ..core.binding_ids import BindingId
    from ..core.source_access import AttachedBindingStages, FileBindingStages


class CurrentStages:
    """Every binding's stages, compared with the bindings before each use if their state was rebuilt since."""

    _registry: StageRegistry
    _pruned_at: int | None  # state.rebuild_count() when the stages were last compared with the bindings

    def __init__(self) -> None:
        self._registry = StageRegistry()
        self._pruned_at = None

    def file(self, binding_id: BindingId, root: str | os.PathLike[str]) -> FileBindingStages:
        """The binding's stages on the file root (StageRegistry.file)."""
        return self._current().file(binding_id, root)

    def attached(self, binding_id: BindingId, key: str) -> AttachedBindingStages:
        """The binding's stages on an attached source (StageRegistry.attached)."""
        return self._current().attached(binding_id, key)

    def get(self, binding_id: BindingId) -> FileBindingStages | AttachedBindingStages | None:
        """The binding's stages, or None before their first use."""
        return self._current().get(binding_id)

    def release(self, key: str) -> None:
        """Release the stage attached under key from every binding with that key (StageRegistry.release)."""
        self._current().release(key)

    def prune(self) -> None:
        """Drop the stages of bindings that no longer exist or can't synchronize (StageRegistry.prune).

        With no stages, as before a session's first synchronization, it reads no configurations, so calling it
        (as the undo and redo handler does) never rebuilds the bindings' state.
        """
        if self._registry:
            # A disabled binding's file source goes, as an unreadable one's does: neither synchronizes.
            configs = binding_configs.configs()
            self._registry.prune({binding_id: isinstance(c, BindingConfig) for binding_id, c in configs.items()})
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
