"""Evaluation and planning: a source captured and planned at time codes (pipeline.md#synchronization-layer-boundaries).

A synchronization plans its one time code, and a cache call each it caches. Nothing here changes Blender data, so a
failure only reports: an expected one is a fatal diagnostic, never an exception (API-04). The source's layers are
watched while it's captured, and one that changes meanwhile discards what was captured (CONS-03).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..binding import results
from ..binding.results import Diagnostic, DiagnosticCode
from ..binding.source_access import stages
from ..core import _core

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pxr import Usd

    from ..binding.source_access import BindingId, binding_settings


# The core reports exactly the codes the documented list says it does: a core built against another list fails here, on
# import, rather than at the first diagnostic it reports (DiagnosticCode raises ValueError for one it lacks).
if frozenset(DiagnosticCode(code) for code in _core.diagnostic_codes()) != results.CORE_CODES:
    raise ImportError("The compiled core reports other diagnostic codes than binding.results.CORE_CODES")


def plan_diagnostics(binding_id: BindingId, plan: _core.Plan) -> tuple[Diagnostic, ...]:
    """The plan's source-side diagnostics as the binding's, in its order."""
    return tuple(
        Diagnostic(
            DiagnosticCode(d.code),
            binding_id,
            d.message,
            source_path=d.source_path,
            property_path=d.property_path,
            asset_identifier=d.asset_identifier,
            fallback_description=d.fallback_description,
        )
        for d in plan.diagnostics
    )


def source_state_diagnostics(binding_id: BindingId, evaluation_stage: Usd.Stage) -> tuple[Diagnostic, ...]:
    """The informational diagnostics on the source's state that a display of it reports: its dirty layers."""
    if not (dirty := stages.dirty_layers(evaluation_stage)):
        return ()
    message = "Displaying layers with unsaved in-process edits"
    return (Diagnostic(DiagnosticCode.UNSAVED_LAYERS, binding_id, message, layer_identifiers=tuple(sorted(dirty))),)


def evaluate_display_plans(
    binding_id: BindingId,
    binding_stages: stages.BindingStages,
    evaluation_stage: Usd.Stage,
    settings: binding_settings.RequestedSettings,
    unit_scale: float,
    time_codes: Sequence[Usd.TimeCode],
    *,
    representation_version: int,
) -> list[_core.Plan] | Diagnostic:
    """Evaluate snapshots and build display plans in time-code order, or return a fatal diagnostic.

    evaluation_stage is binding_stages' evaluation stage, acquired under settings' payload policy; the plans apply
    settings' conversion and purposes, and unit_scale, the target scene's. The caller supplies the representation
    version its application layer consumes.
    """
    try:
        with binding_stages.monitor_evaluation_layer_changes() as changed:
            chain = _core.SceneIndexChain(evaluation_stage)
            try:
                snapshots = [chain.capture(time_code) for time_code in time_codes]
            finally:
                chain.release()  # the core never keeps the stage alive
            if changed:  # what was captured may mix the source before and after the change (CONS-03)
                message = "A contributing layer changed during evaluation, so the attempt was discarded"
                return Diagnostic(
                    DiagnosticCode.SOURCE_CHANGED, binding_id, message, layer_identifiers=tuple(sorted(changed))
                )
    except Exception as error:  # noqa: BLE001 - any failure is the attempt's fatal diagnostic
        return Diagnostic(DiagnosticCode.EVALUATION_FAILED, binding_id, f"Evaluating the source failed: {error}")
    try:
        planned = _core.PlanSettings(
            settings.viewport_purposes, settings.render_purposes, settings.coordinate_conversion
        )
        context = _core.PlanningContext(unit_scale, representation_version)
        return [_core.plan(snapshot, planned, context) for snapshot in snapshots]
    except Exception as error:  # noqa: BLE001
        return Diagnostic(DiagnosticCode.PLANNING_FAILED, binding_id, f"Planning the display failed: {error}")
