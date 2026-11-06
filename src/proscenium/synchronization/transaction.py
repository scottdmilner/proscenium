"""The synchronization transaction: one attempt to display a binding's source (pipeline.md#synchronization-transaction).

Its steps are acquisition, evaluation, planning, preparation, publication, and retirement. A binding whose records an
attempt needs can't be read is refused before its source is read, so nothing they name is replaced or retired. A
failure at any step before publication leaves the published generation as it was and disposes of prepared work, and
an expected failure is a fatal diagnostic, never an exception (API-04). Every attempt the last attempt can record ends
by recording it, whatever its outcome (STATE-03). Retirement is the M5 plan's D7.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..binding.persistence import binding_state, ledgers, manifests, records
from ..binding.results import Diagnostic, DiagnosticCode, Result
from ..binding.runtime import binding_configs, ownership_index, pending_cleanup
from ..binding.source_access import stages
from ..core import _core
from . import application, prepared_work, publication

if TYPE_CHECKING:
    import bpy
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
    record = binding_configs.required_record(binding_id)
    scene = record.scene
    if isinstance(last := binding_state.read_last_attempt(scene, binding_id), records.RefusedRecord):
        # Kept, so this attempt goes unrecorded.
        return Result(Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, last.message), time_codes=(time_code,))
    # A synchronization writes the binding's records, so it restores a lost index entry first, as every write does,
    # giving the ledger a Text to be on.
    binding_configs.restore_entry(binding_id, record)
    result = Result(*_attempt(binding_id, config, scene, current, time_code), time_codes=(time_code,))
    stored_time = binding_state.stored_time(time_code)
    attempt = binding_state.LastAttempt(config.settings.payload_policy, stored_time, result.diagnostics)
    binding_state.write_last_attempt(scene, binding_id, attempt)
    return result


def _attempt(
    binding_id: identifiers.BindingId,
    config: configs.BindingConfig,
    scene: bpy.types.Scene,
    current: stage_tracking.CurrentStages,
    time_code: Usd.TimeCode,
) -> tuple[Diagnostic, ...]:
    """The attempt's diagnostics, its steps run as far as they succeed."""
    if (destination := config.destination) is None:  # removed: Blender cleared the pointer (lifecycle.md)
        message = f"The destination collection of binding {binding_id} was removed"
        return (Diagnostic(DiagnosticCode.REMOVED_DESTINATION, binding_id, message),)
    # A manifest naming an unknown role is one that can't be read (ROLE-01).
    manifest = ownership_index.manifest(binding_id)
    generation = binding_state.read_generation(destination)
    if isinstance(manifest, records.RefusedRecord):
        return (Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, manifest.message),)
    if isinstance(generation, records.RefusedRecord):
        return (Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, generation.message),)
    if (refused := _untracked(binding_id)) is not None:
        return (refused,)
    policy = config.settings.payload_policy
    stages_ = current.attached(binding_id)
    try:
        evaluation = stages_.acquire(policy)
    except stages.SourceUnavailableError as error:
        return (Diagnostic(DiagnosticCode.NO_ATTACHED_STAGE, binding_id, str(error)),)
    revision = stages_.source_revision
    own: tuple[Diagnostic, ...] = ()
    if dirty := stages.dirty_layers(evaluation):
        message = "Displaying layers with unsaved in-process edits"
        own = (Diagnostic(DiagnosticCode.UNSAVED_LAYERS, binding_id, message, layers=tuple(sorted(dirty))),)

    # Before preparation nothing in Blender has changed, so a failure only reports.
    try:
        chain = _core.SceneIndexChain(evaluation)
        try:
            snapshot = chain.capture(time_code)
        finally:
            chain.release()  # the core never keeps the stage alive
    except Exception as error:  # noqa: BLE001 - any failure is the attempt's fatal diagnostic
        failed = Diagnostic(DiagnosticCode.EVALUATION_FAILED, binding_id, f"Evaluating the source failed: {error}")
        return (*own, failed)
    try:
        context = _core.PlanningContext(scene.unit_settings.scale_length, application.REPRESENTATION_VERSION)
        plan = _core.plan(snapshot, context)
    except Exception as error:  # noqa: BLE001
        failed = Diagnostic(DiagnosticCode.PLANNING_FAILED, binding_id, f"Planning the display failed: {error}")
        return (*own, failed)

    work = prepared_work.new_prepared_work(binding_id, ledgers.OriginatingOperation.SYNCHRONIZE)
    published = manifests.Manifest({}) if manifest is None else manifest.record
    try:
        application.prepare(plan, published, work)
    except Exception as error:  # noqa: BLE001
        failed = Diagnostic(DiagnosticCode.PREPARATION_FAILED, binding_id, f"Preparing the display failed: {error}")
        return (*own, failed, *prepared_work.dispose(work))
    described = binding_state.Generation(
        binding_id, policy, binding_state.stored_time(time_code), revision, Result(*own).diagnostics
    )
    try:
        publication.publish(binding_id, destination, work, described)
    except Exception as error:  # noqa: BLE001
        failed = Diagnostic(DiagnosticCode.PUBLICATION_FAILED, binding_id, f"Publishing the display failed: {error}")
        return (*own, failed, *prepared_work.dispose(work))
    prepared_work.remove_staging(work)
    return own


def _untracked(binding_id: identifiers.BindingId) -> Diagnostic | None:
    """Why the ledger can't track what preparation makes, or None if it can (pending_cleanup.check_trackable)."""
    try:
        pending_cleanup.check_trackable()
    except records.RefusedRecordError as error:
        return Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, error.refused.message)
    except ValueError as error:
        return Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, str(error))
    return None
