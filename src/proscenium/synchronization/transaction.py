"""The synchronization transaction: one attempt to display a binding's source (pipeline.md#synchronization-transaction).

Its steps are acquisition, evaluation, planning, preparation, publication, and retirement. A binding whose records an
attempt needs can't be read is refused before its source is read, so nothing they name is replaced or retired. A
failure at any step before publication leaves the published generation as it was and disposes of prepared work, and
an expected failure is a fatal diagnostic, never an exception (API-04). Every attempt the last attempt can record ends
by recording it, whatever its outcome (STATE-03). An attempt during whose evaluation a contributing layer changed is
discarded before publication (CONS-03). After publication, a resource retirement can't remove leaves the
synchronization completed with issues (TXN-07). A ledger write that fails as disposal or retirement records its
leftovers is a defect, and raises (pipeline.md#synchronization-transaction).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pxr import Usd

from ..binding.persistence import binding_state, cleanup_ledgers, id_property_records, manifests
from ..binding.results import Diagnostic, DiagnosticCode, Result
from ..binding.runtime import binding_operations
from ..binding.source_access import stages
from . import application, evaluation, preparation_resources, publication, retirement

if TYPE_CHECKING:
    import bpy

    from ..binding.persistence import binding_records
    from ..binding.runtime import stage_tracking
    from ..binding.source_access import binding_ids


def synchronize(
    binding_id: binding_ids.BindingId,
    config: binding_records.BindingConfig,
    current: stage_tracking.BindingStageTracker,
    time_code: Usd.TimeCode | None,
) -> Result:
    """Synchronize a usable binding with config at time_code; the result names the time code.

    Without a time code, the attempt is at the target scene's current frame's, its subframe included, since time code
    t is frame t (transforms.md#transforms-and-time-codes). The binding's stages are current's, made only once the
    source is accessed, so a binding failing before that gets none.
    """
    record = binding_operations.require_canonical_binding_record(binding_id)
    scene, destination = config.scene, record.collection
    assert scene is not None  # a binding's candidate names a target scene that exists
    if time_code is None:
        time_code = Usd.TimeCode(scene.frame_current + scene.frame_subframe)
    if isinstance(last := binding_state.read_last_attempt(destination), id_property_records.RefusedRecord):
        # Kept, so this attempt goes unrecorded.
        return Result(
            Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, last.message), attempted_time_codes=(time_code,)
        )
    # A synchronization writes the binding's records, so it restores a lost index entry first, as every write does,
    # giving the ledger a Text to be on.
    binding_operations.restore_missing_binding_index_entry(binding_id, record)
    result = Result(*_attempt(binding_id, config, destination, current, time_code), attempted_time_codes=(time_code,))
    encoded_time_code = binding_state.encode_time_code(time_code)
    attempt = binding_state.LastSynchronizationAttempt(config.requested_settings, encoded_time_code, result.diagnostics)
    binding_state.write_last_attempt(destination, attempt)
    return result


def _attempt(
    binding_id: binding_ids.BindingId,
    config: binding_records.BindingConfig,
    destination: bpy.types.Collection,
    current: stage_tracking.BindingStageTracker,
    time_code: Usd.TimeCode,
) -> tuple[Diagnostic, ...]:
    """The attempt's diagnostics, its steps run as far as they succeed."""
    scene = config.scene
    assert scene is not None
    # A manifest naming an unknown role is one that can't be read (ROLE-01).
    manifest = manifests.read_manifest(destination)
    generation = binding_state.read_generation(destination)
    if isinstance(manifest, id_property_records.RefusedRecord):
        return (Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, manifest.message),)
    if isinstance(generation, id_property_records.RefusedRecord):
        return (Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, generation.message),)
    if (refused := preparation_resources.cleanup_tracking_diagnostic(binding_id)) is not None:
        return (refused,)
    settings, unit_scale = config.requested_settings, scene.unit_settings.scale_length
    stages_ = current.get_or_create_binding_stages(binding_id)
    try:
        evaluation_stage = stages_.acquire_evaluation_stage(settings.payload_policy)
    except stages.SourceUnavailableError as error:
        return (Diagnostic(DiagnosticCode.NO_ATTACHED_STAGE, binding_id, str(error)),)
    revision = stages_.source_revision
    own = evaluation.source_state_diagnostics(binding_id, evaluation_stage)
    # Before preparation nothing in Blender has changed, so a failure only reports.
    planned = evaluation.evaluate_display_plans(
        binding_id,
        stages_,
        evaluation_stage,
        settings,
        unit_scale,
        (time_code,),
        representation_version=application.REPRESENTATION_VERSION,
    )
    if isinstance(planned, Diagnostic):
        return (*own, planned)
    [plan] = planned
    own = (*own, *evaluation.plan_diagnostics(binding_id, plan))  # content's, so they join the generation's too

    work = preparation_resources.new_preparation_resources(binding_id, cleanup_ledgers.OriginatingOperation.SYNCHRONIZE)
    published = manifests.Manifest({}) if manifest is None else manifest.record
    try:
        application.prepare(plan, published, work)
    except Exception as error:  # noqa: BLE001
        failed = Diagnostic(DiagnosticCode.PREPARATION_FAILED, binding_id, f"Preparing the display failed: {error}")
        return (*own, failed, *preparation_resources.dispose(work))
    described = binding_state.GenerationMetadata(
        binding_id, settings, unit_scale, binding_state.encode_time_code(time_code), revision, Result(*own).diagnostics
    )
    try:
        before = None if manifest is None else published
        previous = None if generation is None else generation.record
        obsolete = publication.publish(destination, work, described, before, previous)
    except Exception as error:  # noqa: BLE001
        failed = Diagnostic(DiagnosticCode.PUBLICATION_FAILED, binding_id, f"Publishing the display failed: {error}")
        return (*own, failed, *preparation_resources.dispose(work))
    preparation_resources.remove_staging_and_clear_tracking(work)
    return (*own, *retirement.retire(binding_id, obsolete, work.operation))
