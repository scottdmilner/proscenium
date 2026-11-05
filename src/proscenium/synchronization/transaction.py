"""The synchronization transaction: one attempt to display a binding's source (pipeline.md#synchronization-transaction).

Its steps are acquisition, evaluation, planning, preparation, publication, and retirement. So far it checks that the
binding's manifest can be read and acquires: the M5 plan's Phase D adds the rest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..binding.persistence import records
from ..binding.results import Diagnostic, DiagnosticCode, Result
from ..binding.runtime import ownership_index
from ..binding.source_access import stages

if TYPE_CHECKING:
    from pxr import Usd

    from ..binding.persistence import configs
    from ..binding.runtime import stage_tracking
    from ..binding.source_access import identifiers


def synchronize(
    binding_id: identifiers.BindingId,
    config: configs.BindingConfig,
    current: stage_tracking.CurrentStages,
    time_code: Usd.TimeCode,
) -> Result:
    """Synchronize a usable binding with config at time_code; the result names the time code.

    The binding's stages are current's, made only once the source is accessed, so a binding failing before that
    gets none.
    """
    if config.destination is None:  # removed: Blender cleared the pointer (lifecycle.md#removed-destination)
        message = f"The destination collection of binding {binding_id} was removed"
        return Result(Diagnostic(DiagnosticCode.REMOVED_DESTINATION, binding_id, message), time_codes=(time_code,))
    # A manifest that can't be read, one naming an unknown role included (ROLE-01), is kept, so nothing it names is
    # replaced or retired.
    if isinstance(manifest := ownership_index.manifest(binding_id), records.RefusedRecord):
        diagnostic = Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, manifest.message)
        return Result(diagnostic, time_codes=(time_code,))
    try:
        dirty = stages.dirty_layers(current.attached(binding_id).acquire(config.settings.payload_policy))
    except stages.SourceUnavailableError as error:
        return Result(Diagnostic(DiagnosticCode.NO_ATTACHED_STAGE, binding_id, str(error)), time_codes=(time_code,))
    if not dirty:
        return Result(time_codes=(time_code,))
    message = "Displaying layers with unsaved in-process edits"
    diagnostic = Diagnostic(DiagnosticCode.UNSAVED_LAYERS, binding_id, message, layers=tuple(sorted(dirty)))
    return Result(diagnostic, time_codes=(time_code,))
