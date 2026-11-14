"""What the API's helper modules read of the process's bindings, which bindings.Bindings provides.

binding_interaction, scene_source_selection, and binding_status take the process's bindings as this protocol, not as
Bindings itself, so bindings.py can import them without either needing the other (tests/bpy_free/test_import_tiers.py
forbids a cycle within a unit, a type-only import's included).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    import bpy
    from pxr import Usd

    from ..binding.runtime import held_plans
    from ..binding.source_access import BindingId


class ProcessBindings(Protocol):
    """The process's bindings, as the API's helper modules read them."""

    published_plans: held_plans.HeldPlans  # published generations' plans, held this session
    running: bool  # whether an exclusive operation is running
    selection_listeners: list[Callable[[bpy.types.Scene], None]]  # called once per change to a scene's selection

    def live_stage(self, binding_id: BindingId) -> Usd.Stage | None:
        """The binding's live stage, or None when unattached or unusable."""
        ...

    def possibly_out_of_date(self, binding_id: BindingId) -> bool:
        """Whether the binding's display may not show its source as it is now."""
        ...
