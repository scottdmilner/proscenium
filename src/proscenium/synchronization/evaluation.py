"""Evaluation and planning: a source captured and planned at time codes (pipeline.md#synchronization-layer-boundaries).

A synchronization plans its one time code, and a cache call each it caches. Nothing here changes Blender data, so a
failure only reports: an expected one is a fatal diagnostic, never an exception (API-04). The source's layers are
watched while it's captured, and one that changes meanwhile discards what was captured (CONS-03).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..binding.results import Diagnostic, DiagnosticCode
from ..binding.source_access import stages
from ..core import _core
from . import application

if TYPE_CHECKING:
    from collections.abc import Sequence

    import bpy
    from pxr import Usd

    from ..binding.source_access import identifiers


def source_state(binding_id: identifiers.BindingId, evaluation_stage: Usd.Stage) -> tuple[Diagnostic, ...]:
    """The informational diagnostics on the source's state that a display of it reports: its dirty layers."""
    if not (dirty := stages.dirty_layers(evaluation_stage)):
        return ()
    message = "Displaying layers with unsaved in-process edits"
    return (Diagnostic(DiagnosticCode.UNSAVED_LAYERS, binding_id, message, layers=tuple(sorted(dirty))),)


def plans(
    binding_id: identifiers.BindingId,
    binding_stages: stages.BindingStages,
    evaluation_stage: Usd.Stage,
    scene: bpy.types.Scene,
    time_codes: Sequence[Usd.TimeCode],
) -> list[_core.Plan] | Diagnostic:
    """The display's plan at each of time_codes, in their order, or the fatal diagnostic saying why there are none.

    evaluation_stage is binding_stages' evaluation stage, acquired; scene is the target scene, whose unit scale the
    plans apply.
    """
    try:
        with binding_stages.changed_layers() as changed:
            chain = _core.SceneIndexChain(evaluation_stage)
            try:
                snapshots = [chain.capture(time_code) for time_code in time_codes]
            finally:
                chain.release()  # the core never keeps the stage alive
            if changed:  # what was captured may mix the source before and after the change (CONS-03)
                message = "A contributing layer changed during evaluation, so the attempt was discarded"
                return Diagnostic(DiagnosticCode.SOURCE_CHANGED, binding_id, message, layers=tuple(sorted(changed)))
    except Exception as error:  # noqa: BLE001 - any failure is the attempt's fatal diagnostic
        return Diagnostic(DiagnosticCode.EVALUATION_FAILED, binding_id, f"Evaluating the source failed: {error}")
    try:
        # The spec's default purposes (DECISIONS.md "Conversion and purpose settings"); D2 passes the binding's own.
        settings = _core.PlanSettings(("default", "proxy"), ("default", "render"))
        context = _core.PlanningContext(scene.unit_settings.scale_length, application.REPRESENTATION_VERSION)
        return [_core.plan(snapshot, settings, context) for snapshot in snapshots]
    except Exception as error:  # noqa: BLE001
        return Diagnostic(DiagnosticCode.PLANNING_FAILED, binding_id, f"Planning the display failed: {error}")
