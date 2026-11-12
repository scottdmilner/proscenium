"""Evaluation and planning: a source captured and planned at time codes (pipeline.md#synchronization-layer-boundaries).

A synchronization plans its one time code, and a cache call each it caches. Nothing here changes Blender data, so a
failure only reports: an expected one is a fatal diagnostic, never an exception (API-04). The source's layers are
watched while it's captured, and one that changes meanwhile discards what was captured (CONS-03).

Each capture is from the binding's kept chain (BindingStages.keep_chain), which synchronizations and cache calls share,
built when there is none. A capture that fails or is discarded releases it, so the next is from a new chain. Under the
opt-in verification mode (capture_verification), a capture from a kept chain is also made through a new one, which is
kept in its place where their plans differ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..binding import results
from ..binding.results import Diagnostic, DiagnosticCode
from ..binding.source_access import stages
from ..core import _core
from . import capture_verification

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


@dataclass(frozen=True, slots=True)
class DisplayPlans:
    """The plans evaluation built, in time-code order, and the verification diagnostics it reports with them."""

    plans: list[_core.Plan]
    verification_diagnostics: tuple[Diagnostic, ...] = ()


def evaluate_display_plans(
    binding_id: BindingId,
    binding_stages: stages.BindingStages,
    evaluation_stage: Usd.Stage,
    settings: binding_settings.RequestedSettings,
    unit_scale: float,
    time_codes: Sequence[Usd.TimeCode],
    *,
    representation_version: int,
    new_chain: bool = False,
) -> DisplayPlans | Diagnostic:
    """Evaluate snapshots and build display plans in time-code order, or return a fatal diagnostic.

    evaluation_stage is binding_stages' evaluation stage, acquired under settings' payload policy; the plans apply
    settings' conversion and purposes, and unit_scale, the target scene's. The caller supplies the representation
    version its application layer consumes. With new_chain, the kept chain is released first, so the capture is from
    a new one, which copies every prim. Under the verification mode, a capture from a kept chain is checked against one
    through a new chain (capture_verification).
    """
    if new_chain:
        binding_stages.release_kept_chain()
    fresh: _core.SceneIndexChain | None = None  # the verification mode's new chain, released unless kept
    try:
        try:
            with binding_stages.monitor_evaluation_layer_changes() as changed:
                try:
                    chain, built = _kept_chain(binding_stages, evaluation_stage)
                    snapshots = [chain.capture(time_code) for time_code in time_codes]
                    if not built and capture_verification.enabled():
                        fresh = _core.SceneIndexChain(evaluation_stage)
                    full_snapshots = [] if fresh is None else [fresh.capture(time_code) for time_code in time_codes]
                except BaseException:
                    binding_stages.release_kept_chain()  # it may have applied only some of the stage's edits
                    raise
                if changed:  # what was captured may mix the source before and after the change (CONS-03)
                    binding_stages.release_kept_chain()
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
            plans = [_core.plan(snapshot, planned, context) for snapshot in snapshots]
            full_plans = [_core.plan(snapshot, planned, context) for snapshot in full_snapshots]
        except Exception as error:  # noqa: BLE001
            return Diagnostic(DiagnosticCode.PLANNING_FAILED, binding_id, f"Planning the display failed: {error}")
        return (
            DisplayPlans(plans)
            if fresh is None
            else _verified(binding_id, binding_stages, fresh, time_codes, plans, full_plans)
        )
    finally:
        if fresh is not None and binding_stages.kept_chain is not fresh:
            fresh.release()


def _verified(
    binding_id: BindingId,
    binding_stages: stages.BindingStages,
    fresh: _core.SceneIndexChain,
    time_codes: Sequence[Usd.TimeCode],
    plans: list[_core.Plan],
    full_plans: list[_core.Plan],
) -> DisplayPlans:
    """The kept chain's plans if they equal the full re-read's; otherwise the full re-read's, its chain kept instead."""
    mismatches = capture_verification.mismatch_diagnostics(binding_id, time_codes, plans, full_plans)
    if not mismatches:
        return DisplayPlans(plans)
    binding_stages.keep_chain(fresh)  # what the kept chain missed may have left its own values stale
    return DisplayPlans(full_plans, mismatches)


def _kept_chain(
    binding_stages: stages.BindingStages, evaluation_stage: Usd.Stage
) -> tuple[_core.SceneIndexChain, bool]:
    """The binding's kept chain over evaluation_stage, built and kept when there is none, and whether it was built."""
    chain = binding_stages.kept_chain
    if isinstance(chain, _core.SceneIndexChain) and not chain.released:
        return chain, False
    chain = _core.SceneIndexChain(evaluation_stage)
    binding_stages.keep_chain(chain)
    return chain, True
