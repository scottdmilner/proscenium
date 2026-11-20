"""What the API's helper modules read of the process's bindings, which binding_service.Bindings provides.

binding_interaction, scene_source_selection, and binding_status take the process's bindings as this protocol, not as
Bindings itself, so binding_service.py can import them without either needing the other (import-linter forbids a
cycle within a unit, a type-only import's included).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    import bpy
    from pxr import Usd

    from proscenium_sync.persistence.binding_state import GenerationMetadata
    from proscenium_sync.runtime import held_plans, stage_tracking
    from proscenium_sync.source_access import BindingId

    from .shown_displays import ShownDisplays


class ProcessBindings(Protocol):
    """The process's bindings, as the API's helper modules read them."""

    stages: stage_tracking.BindingStageTracker  # each binding's stages, this session
    published_plans: held_plans.HeldPlans  # published generations' plans, held this session
    published: dict[BindingId, GenerationMetadata]  # each binding's last generation published this session
    shown_displays: ShownDisplays  # each binding's display, kept for interaction calls
    running: bool  # whether an exclusive operation is running
    selection_listeners: list[Callable[[bpy.types.Scene], None]]  # called once per change to a scene's selection

    def live_stage(self, binding_id: BindingId) -> Usd.Stage | None:
        """The binding's live stage, or None when unattached or unusable."""
        ...
