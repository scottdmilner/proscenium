"""The synchronization transaction: one attempt to display a binding's source (pipeline.md#synchronization-transaction).

Its steps are acquisition, evaluation, planning, preparation, publication, and retirement. A binding whose records an
attempt needs can't be read is refused before its source is read, so nothing they name is replaced or retired. A
failure at any step before publication leaves the published generation as it was and disposes of prepared work, and
an expected failure is a fatal diagnostic, never an exception (API-04). Every attempt the last attempt can record ends
by recording it, whatever its outcome (STATE-03). An attempt during whose evaluation a contributing layer changed is
discarded before publication (CONS-03). A destination also linked into a scene whose unit scale differs from the
target scene's, which the display is planned for, gets a warning before anything in Blender changes (CONV-07). A
failure only application detects aborts the attempt, since the plan
authorizes no fallback: a resource operation failing, as preparation-failed naming the resource, and the destination
removed during preparation, as destination-invalid, after which no last attempt is recorded, its records gone with
it (APP-05, APP-06). After publication, a resource retirement can't remove leaves the synchronization completed with
issues (TXN-07). A ledger write that fails as disposal or retirement records its leftovers is a defect, and raises
(pipeline.md#synchronization-transaction).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
from pxr import Usd

from ..binding.persistence import binding_state, cleanup_ledgers, id_property_records, manifests
from ..binding.results import Diagnostic, DiagnosticCode, DiagnosticCollector, Result
from ..binding.runtime import binding_operations
from ..binding.source_access import stages
from . import application, evaluation, preparation_resources, publication, retirement

if TYPE_CHECKING:
    from ..binding.persistence import binding_records
    from ..binding.runtime import held_plans, stage_tracking
    from ..binding.source_access import BindingId


def synchronize(
    binding_id: BindingId,
    config: binding_records.BindingConfig,
    current: stage_tracking.BindingStageTracker,
    published_plans: held_plans.HeldPlans,
    time_code: Usd.TimeCode | None,
    *,
    full_rebuild: bool = False,
) -> Result:
    """Synchronize a usable binding with config at time_code; the result names the time code.

    Without a time code, the attempt is at the target scene's current frame's, its subframe included, since time code
    t is frame t (transforms.md#transforms-and-time-codes). The binding's stages are current's, made only once the
    source is accessed, so a binding failing before that gets none. A published generation's plan is held in
    published_plans, as many per binding as Blender's undo steps allow and the generation shown. A full rebuild captures
    through a new chain and prepares every partition (source-access.md#synchronization-api), as every synchronization
    does until incremental refresh replaces only what changed.
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
    report = DiagnosticCollector()
    _attempt(binding_id, config, destination, current, published_plans, time_code, report, full_rebuild=full_rebuild)
    result = report.result(attempted_time_codes=(time_code,))
    if _removed(destination):  # removed during the attempt, with its records, so there's nothing to record on
        return result
    encoded_time_code = binding_state.encode_time_code(time_code)
    attempt = binding_state.LastSynchronizationAttempt(config.requested_settings, encoded_time_code, result.diagnostics)
    binding_state.write_last_attempt(destination, attempt)
    return result


def _attempt(
    binding_id: BindingId,
    config: binding_records.BindingConfig,
    destination: bpy.types.Collection,
    current: stage_tracking.BindingStageTracker,
    published_plans: held_plans.HeldPlans,
    time_code: Usd.TimeCode,
    report: DiagnosticCollector,
    *,
    full_rebuild: bool,
) -> None:
    """Run the attempt's steps as far as they succeed, reporting its diagnostics to report."""
    scene = config.scene
    assert scene is not None
    # A manifest naming an unknown role is one that can't be read (ROLE-01).
    manifest = manifests.read_manifest(destination)
    generation = binding_state.read_generation(destination)
    if isinstance(manifest, id_property_records.RefusedRecord):
        report.add(Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, manifest.message))
        return
    if isinstance(generation, id_property_records.RefusedRecord):
        report.add(Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, generation.message))
        return
    if (refused := preparation_resources.cleanup_tracking_diagnostic(binding_id)) is not None:
        report.add(refused)
        return
    settings, unit_scale = config.requested_settings, scene.unit_settings.scale_length
    # Found before anything in Blender changes, and the display's, so the generation records them too (CONV-07).
    mismatches = _unit_scale_mismatches(binding_id, destination, scene)
    stages_ = current.get_or_create_binding_stages(binding_id)
    try:
        evaluation_stage = stages_.acquire_evaluation_stage(settings.payload_policy)
    except stages.SourceUnavailableError as error:
        report.add(Diagnostic(DiagnosticCode.NO_ATTACHED_STAGE, binding_id, str(error)))
        return
    revision = stages_.source_revision
    report.extend(mismatches)
    # Before preparation nothing in Blender has changed, so a failure only reports. Evaluation's diagnostics are the
    # content's, the source state's, and the verification mode's, so the generation records them too.
    plans = evaluation.evaluate_display_plans(
        binding_id,
        stages_,
        evaluation_stage,
        settings,
        unit_scale,
        (time_code,),
        report,
        representation_version=application.REPRESENTATION_VERSION,
        new_chain=full_rebuild,  # whatever the kept chain missed, a new one reads (incremental.md#change-discovery)
    )
    if plans is None:
        return
    [plan] = plans

    work = preparation_resources.new_preparation_resources(binding_id, cleanup_ledgers.OriginatingOperation.SYNCHRONIZE)
    published = manifests.Manifest({}) if manifest is None else manifest.record
    destination_name = destination.name  # for a diagnostic if it's removed meanwhile
    # A failure only application detects aborts the attempt, since the plan authorizes no fallback (APP-05, APP-06).
    try:
        application.prepare(plan, range(plan.copy_count), published, work)
    except application.ResourceOperationError as error:  # a runtime failure, naming its resource
        message = f"Preparing the display failed: {error}"
        failed = Diagnostic(
            DiagnosticCode.PREPARATION_FAILED,
            binding_id,
            message,
            source_path=error.source_entity_path,
            role=str(error.role),
        )
        preparation_resources.abort(report, failed, work)
        return
    except Exception as error:  # noqa: BLE001
        failed = Diagnostic(DiagnosticCode.PREPARATION_FAILED, binding_id, f"Preparing the display failed: {error}")
        preparation_resources.abort(report, failed, work)
        return
    if _removed(destination):  # a state change
        message = f"The destination collection {destination_name!r} was removed while the display was prepared"
        failed = Diagnostic(DiagnosticCode.DESTINATION_INVALID, binding_id, message)
        preparation_resources.abort(report, failed, work)
        return
    described = binding_state.GenerationMetadata(
        binding_id, settings, unit_scale, binding_state.encode_time_code(time_code), revision, report.diagnostics
    )
    try:
        before = None if manifest is None else published
        previous = None if generation is None else generation.record
        obsolete = publication.publish(destination, work, described, before, previous)
    except Exception as error:  # noqa: BLE001
        failed = Diagnostic(DiagnosticCode.PUBLICATION_FAILED, binding_id, f"Publishing the display failed: {error}")
        preparation_resources.abort(report, failed, work)
        return
    published_plans.hold(described, plan, _held_plan_bound())
    preparation_resources.remove_staging_and_clear_tracking(work)
    report.extend(retirement.retire(binding_id, obsolete, work.operation))


def _held_plan_bound() -> int:
    """How many plans a binding holds: the generation shown, and one for each undo step Blender keeps."""
    preferences = bpy.context.preferences
    assert preferences is not None  # Blender's, which a running Blender, and the bpy module, always has
    return preferences.edit.undo_steps + 1


def _unit_scale_mismatches(
    binding_id: BindingId, destination: bpy.types.Collection, target: bpy.types.Scene
) -> tuple[Diagnostic, ...]:
    """A diagnostic for each other scene linking the destination whose unit scale differs from the target scene's.

    The display is planned for the target scene's scale, so in such a scene it shows at the wrong one; it isn't
    guessed which is meant (transforms.md#coordinate-conversion).
    """
    scale = target.unit_settings.scale_length
    return tuple(
        Diagnostic(
            DiagnosticCode.UNIT_SCALE_MISMATCH,
            binding_id,
            f"The destination collection {destination.name!r} is also linked into scene {other.name!r}, whose unit "
            f"scale {other.unit_settings.scale_length:g} differs from the target scene {target.name!r}'s {scale:g}, "
            "which the display is planned for",
        )
        for other in bpy.data.scenes
        if other != target
        and other.unit_settings.scale_length != scale
        and destination in other.collection.children_recursive
    )


def _removed(destination: bpy.types.Collection) -> bool:
    """Whether the destination collection has been removed from the file, so it's no longer valid."""
    try:
        destination.name  # noqa: B018 - reading a removed ID's property raises
    except ReferenceError:
        return True
    return False
