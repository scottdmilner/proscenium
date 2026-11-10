"""Every binding's stages, kept consistent with the bindings that exist (source-access.md#source-stages).

The stages are source access's StageRegistry, created unattached on first use by binding identity. Each use first
drops the evaluation stages of bindings that are gone, keeping their attachments for undo and redo
(StageRegistry.prune), which reads the binding records only while there are stages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..source_access import stage_registry
from . import copy_detection

if TYPE_CHECKING:
    from ..source_access import identifiers, stages


class BindingStageTracker:
    """Track binding stages and drop vanished bindings' evaluation stages before each lookup."""

    _registry: stage_registry.StageRegistry

    def __init__(self) -> None:
        self._registry = stage_registry.StageRegistry()

    def get_or_create_binding_stages(self, binding_id: identifiers.BindingId) -> stages.BindingStages:
        """Return the binding's stages, creating unattached state after pruning vanished bindings."""
        self.prune()
        return self._registry.get_or_create_binding_stages(binding_id)

    def get(self, binding_id: identifiers.BindingId) -> stages.BindingStages | None:
        """The binding's stages, or None before their first use."""
        self.prune()
        return self._registry.get(binding_id)

    def release(self, binding_id: identifiers.BindingId) -> None:
        """Release one binding without reading its records (StageRegistry.release)."""
        self._registry.release(binding_id)

    def prune(self) -> None:
        """Drop evaluation stages of bindings that no longer exist (StageRegistry.prune).

        With no stages, as before a session's first synchronization, it reads no records.
        """
        if self._registry:
            self._registry.prune(copy_detection.candidates_by_binding().keys())

    def clear(self) -> None:
        """Drop every binding's stages, leaving each binding with no source stage or attachment."""
        self._registry = stage_registry.StageRegistry()
