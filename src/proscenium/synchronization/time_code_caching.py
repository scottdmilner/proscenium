"""Caching time codes in a binding's published generation, without synchronizing (pipeline.md#cached-time-codes).

A cache call evaluates and plans the source at each time code the generation hasn't cached, under the generation's
settings, before changing any Blender data, so its source-state diagnostics exist before then, as a synchronization's
do. What varies is what differs: each plan is compared with the generation's own, held since it was published
(binding.runtime.held_plans), through the core's plan diff, and a copy a cached time code moves, rebuilds, or shows
otherwise, or one keyed already, varies (DECISIONS.md "What a cache call keys"). time_code_keying then keys those copies
at every time code the generation holds, and the generation record gains the call's. Without the generation's plan held,
as after an undo past the held plans, every copy is keyed. It publishes no new generation, records no last attempt, and
pushes no undo step, as Bindings pushes none for it.

A call that fails caches none of its time codes (CACHE-03): before then a failure only reports, and after it the keys
the call added are removed, the manifest restored, and the actions it made disposed of under the transaction's rules,
each whose removal fails entering the pending-cleanup ledger. A failure is a fatal diagnostic, never an exception,
apart from a ledger write that fails, a defect, which raises.
"""

from __future__ import annotations

import dataclasses
import functools
from typing import TYPE_CHECKING

from pxr import Usd

from ..binding.persistence import binding_state, cleanup_ledgers, id_property_records, manifests
from ..binding.results import Diagnostic, DiagnosticCode, DiagnosticCollector, Result
from ..binding.runtime import binding_operations, kept_manifests, ownership
from ..binding.source_access import stages
from ..core import _core
from . import application, evaluation, preparation_resources, time_code_keying

if TYPE_CHECKING:
    from collections.abc import Collection

    import bpy

    from ..binding.persistence import binding_records
    from ..binding.runtime import held_plans, stage_tracking
    from ..binding.source_access import BindingId


def cache(
    binding_id: BindingId,
    config: binding_records.BindingConfig,
    current: stage_tracking.BindingStageTracker,
    published_plans: held_plans.HeldPlans,
    time_codes: Collection[Usd.TimeCode],
) -> Result:
    """Cache the published generation's time-varying values at each of time_codes it hasn't cached, all or none.

    config is a usable binding's, and time_codes numeric; published_plans hold the published generations' plans. The
    result names the time codes it attempted, those the
    generation hadn't cached, in order. A generation synchronized at the default time code has nothing to cache, so
    the call succeeds caching nothing (CACHE-06); one with no generation, or whose source changed since it was
    synchronized, or whose target scene's unit scale changed since, needs synchronizing, so the call fails caching
    nothing (CACHE-05, CACHE-12).
    """
    scene, destination = config.scene, binding_operations.require_canonical_binding_record(binding_id).collection
    assert scene is not None  # a binding's candidate names a target scene that exists
    manifest = kept_manifests.read_manifest(destination)
    generation = binding_state.read_generation(destination)
    if (unusable := _unusable_state_diagnostic(binding_id, manifest, generation)) is not None:
        return Result(unusable)
    # Narrowed for the type checker: the diagnostic covers a refused record and a missing generation.
    assert generation is not None and not isinstance(generation, id_property_records.RefusedRecord)
    assert not isinstance(manifest, id_property_records.RefusedRecord)
    published = generation.record
    if published.time_code is None:  # nothing in it varies with time
        return Result()
    new = _uncached_values(published, time_codes)
    attempted = [Usd.TimeCode(t) for t in new]
    if (refused := preparation_resources.cleanup_tracking_diagnostic(binding_id)) is not None:
        return Result(refused, attempted_time_codes=attempted)

    binding_stages = current.get_or_create_binding_stages(binding_id)
    try:
        evaluation_stage = binding_stages.acquire_evaluation_stage(published.applied_settings.payload_policy)
    except stages.SourceUnavailableError as error:
        return Result(
            Diagnostic(DiagnosticCode.NO_ATTACHED_STAGE, binding_id, str(error)), attempted_time_codes=attempted
        )
    # Checked even when every time code is cached, so a call never reports success over a source that changed. The
    # revision changes with anything evaluated: an edit, a reload that rereads a layer, an attachment, the evaluation
    # stage loaded to another payload policy since, or a new process.
    if (stale := _stale_message(binding_stages, published, scene)) is not None:
        return Result(
            Diagnostic(DiagnosticCode.NEEDS_SYNCHRONIZATION, binding_id, stale), attempted_time_codes=attempted
        )
    if not new:
        return Result()
    report = DiagnosticCollector()
    plans = evaluation.evaluate_display_plans(
        binding_id,
        binding_stages,
        evaluation_stage,
        published.applied_settings,
        published.unit_scale,
        attempted,
        report,
        representation_version=application.REPRESENTATION_VERSION,
    )
    if plans is None:
        return report.result(attempted_time_codes=attempted)

    work = preparation_resources.new_preparation_resources(binding_id, cleanup_ledgers.OriginatingOperation.CACHE)
    before = _published_manifest(manifest)
    plans_by_time_code = dict(zip(new, plans, strict=True))
    own = published_plans.plan_for(published)
    unknown = time_code_keying.VaryingCopies(None)  # without the generation's plan, every copy
    varying = unknown if own is None else _varying_copies(own, plans_by_time_code.values(), before)
    try:
        changes = time_code_keying.key_time_codes(
            plans_by_time_code, varying, before, destination, published.time_code, published.cached_time_codes, work
        )
    except Exception as error:  # noqa: BLE001 - any failure is the call's fatal diagnostic
        message = f"Keying the cached time codes failed: {error}"
        failed = Diagnostic(DiagnosticCode.PREPARATION_FAILED, binding_id, message)
        preparation_resources.abort(report, failed, work)
        return report.result(attempted_time_codes=attempted)
    cached = tuple(sorted({*published.cached_time_codes, *new}))
    try:
        # Restored whole, since an update by entry that fails partway may have written some entries.
        work.rollback_actions.append(functools.partial(kept_manifests.write_manifest, destination, before))
        ownership.set_manifest_entries(binding_id, changes, created=work.datablocks, published=before)
        binding_state.write_generation(destination, dataclasses.replace(published, cached_time_codes=cached))
    except Exception as error:  # noqa: BLE001
        message = f"Recording the cached time codes failed: {error}"
        failed = Diagnostic(DiagnosticCode.PUBLICATION_FAILED, binding_id, message)
        preparation_resources.abort(report, failed, work)
        return report.result(attempted_time_codes=attempted)
    preparation_resources.remove_staging_and_clear_tracking(work)
    return report.result(attempted_time_codes=attempted)


def _varying_copies(
    own: _core.Plan, plans: Collection[_core.Plan], published: manifests.Manifest
) -> time_code_keying.VaryingCopies:
    """The copies that vary from own in plans, or that published keys already, by source entity.

    A copy varies when keyed already, or when a plan moves it, rebuilds it, shows it otherwise, changes its bounds,
    lacks it, or has it where own doesn't.
    """
    varying = {
        identity.entity
        for entry in published.entries.values()
        if (identity := entry.identity) is not None and identity.role is manifests.RepresentationRole.ACTION
    }
    own_sources = [entry.source_path for entry in own.correspondence]
    for plan in plans:
        diff = _core.diff_plans(own, plan)
        sources = [entry.source_path for entry in plan.correspondence]
        changed = (
            diff.moved_copy_indices,
            diff.rebuilt_copy_indices,
            diff.participation_changed_copy_indices,
            diff.bounds_changed_copy_indices,
        )
        for buffer in changed:
            with memoryview(buffer) as copies:  # released before returning (SNAP-13)
                varying.update(sources[copy] for copy in copies.tolist())
        with memoryview(diff.previous_copy_indices) as previous:
            varying.update(sources[copy] for copy, old in enumerate(previous.tolist()) if old < 0)
        with memoryview(diff.removed_previous_copy_indices) as removed:
            varying.update(own_sources[old] for old in removed.tolist())
    return time_code_keying.VaryingCopies(varying)


def _unusable_state_diagnostic(
    binding_id: BindingId,
    manifest: id_property_records.LoadedRecord[manifests.Manifest] | id_property_records.RefusedRecord | None,
    generation: id_property_records.LoadedRecord[binding_state.GenerationMetadata]
    | id_property_records.RefusedRecord
    | None,
) -> Diagnostic | None:
    """Why the stored manifest and generation can't be cached in: one is unreadable or there is no generation."""
    for stored in (manifest, generation):
        if isinstance(stored, id_property_records.RefusedRecord):
            return Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, stored.message)
    if generation is None:
        message = "The binding has no published generation to cache time codes in; synchronize it first"
        return Diagnostic(DiagnosticCode.NEEDS_SYNCHRONIZATION, binding_id, message)
    return None


def _uncached_values(published: binding_state.GenerationMetadata, time_codes: Collection[Usd.TimeCode]) -> list[float]:
    """The numeric values of time_codes the generation hasn't cached, sorted."""
    have = {published.time_code, *published.cached_time_codes}
    return sorted({t.GetValue() for t in time_codes} - have)


def _published_manifest(stored: id_property_records.LoadedRecord[manifests.Manifest] | None) -> manifests.Manifest:
    """The stored manifest's value, or an empty manifest if there is none."""
    return manifests.Manifest({}) if stored is None else stored.record


def _stale_message(
    binding_stages: stages.BindingStages, published: binding_state.GenerationMetadata, scene: bpy.types.Scene
) -> str | None:
    """Why the published generation needs synchronizing before caching, or None if it doesn't."""
    if binding_stages.source_revision != published.source_revision:
        return "The source changed since the binding was synchronized; synchronize it before caching time codes"
    # The plans would apply another scale than the display's, so its time codes would disagree (CACHE-12).
    if scene.unit_settings.scale_length != published.unit_scale:
        return "The target scene's unit scale changed since the binding was synchronized; synchronize it first"
    return None
