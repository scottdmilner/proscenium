"""Every binding's stages, by binding identifier: when each is made, kept, and let go.

- Source attachments and evaluation stages are runtime state, never saved in the .blend. Undo retains attachments
  and drops evaluation stages of vanished bindings (UNDO-06).
- A binding's stages are made on first use, and compared with the bindings that exist whenever those may have
  changed (prune).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .binding_stages import BindingStages

if TYPE_CHECKING:
    from collections.abc import Collection

    from .binding_ids import BindingId


class StageRegistry:
    """The stages of the process's bindings, by binding identifier."""

    _stages: dict[BindingId, BindingStages]

    def __init__(self) -> None:
        self._stages = {}

    def attached(self, binding_id: BindingId) -> BindingStages:
        """The binding's stages on an attached source, made unattached if it has none.

        Existing ones keep their attachment.
        """
        found = self._stages.get(binding_id)
        if found is not None:
            return found
        stages = self._stages[binding_id] = BindingStages()
        return stages

    def get(self, binding_id: BindingId) -> BindingStages | None:
        """The binding's stages, or None before their first use."""
        return self._stages.get(binding_id)

    def __contains__(self, binding_id: BindingId) -> bool:
        return binding_id in self._stages

    def __len__(self) -> int:
        return len(self._stages)

    def release(self, binding_id: BindingId) -> None:
        """Release one binding's stages, including an attachment retained after undo or removal."""
        if (stages := self._stages.get(binding_id)) is not None:
            stages.release()

    def prune(self, existing: Collection[BindingId]) -> None:
        """Drop evaluation stages of bindings that are gone, keeping attachments until release(binding_id).

        Bindings whose records are unreadable or disabled still exist and keep their stages.
        """
        for binding_id, stages in self._stages.items():
            if binding_id not in existing:
                # Undo neither restores nor removes attachments (UNDO-06), so redo brings the binding back
                # attached; release(binding_id) still releases it.
                stages.drop_evaluation_stage()
