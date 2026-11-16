"""What a panel shows of each of a scene's bindings, in one call (M7 plan, F2).

Bindings.binding_statuses(scene) gives, for each binding the scene lists, its destination's name, why it can't be used
if it can't, whether a stage is attached, whether its display may be out of date, and how its last attempt ended. A
panel calls it once per draw, rather than the API once per value per binding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..binding.persistence import binding_state, id_property_records
from ..binding.runtime import binding_operations

if TYPE_CHECKING:
    import bpy

    from ..binding.results import ResultState
    from ..binding.source_access import BindingId
    from .process_bindings import ProcessBindings


@dataclass(frozen=True, slots=True)
class BindingStatus:
    """One binding as a panel shows it."""

    binding_id: BindingId
    name: str | None  # its destination's name; None for a binding disabled by its copies, which has none
    refusal: str | None  # why it can't be used, a configuration that can't be read or copies, or None if it can
    attached: bool  # whether a caller's stage is attached
    possibly_out_of_date: bool  # whether its display may not show its source as it is now; True if it can't be used
    published: bool  # whether its destination shows a published generation
    last_attempt: ResultState | None  # how its last synchronization ended; None before any, or if it can't be read


def binding_statuses(bindings: ProcessBindings, scene: bpy.types.Scene) -> list[BindingStatus]:
    """The status of each binding the scene lists, in Bindings.in_scene's order."""
    statuses = []
    for found in binding_operations.find_bindings(scene):
        destination = found.destination
        refusal = None
        if found.configuration_refusal is not None:
            refusal = found.configuration_refusal.message
        elif found.disabled_candidate_report is not None:
            refusal = f"Copies with no canonical candidate: {found.disabled_candidate_report.reason}"
        attempt = None if destination is None else binding_state.read_last_attempt(destination)
        generation = None if destination is None else binding_state.read_generation(destination)
        statuses.append(
            BindingStatus(
                binding_id=found.binding_id,
                name=None if destination is None else destination.name,
                refusal=refusal,
                attached=found.usable and bindings.live_stage(found.binding_id) is not None,
                possibly_out_of_date=not found.usable or bindings.possibly_out_of_date(found.binding_id),
                published=isinstance(generation, id_property_records.LoadedRecord),
                last_attempt=attempt.record.result_state
                if isinstance(attempt, id_property_records.LoadedRecord)
                else None,
            )
        )
    return statuses
