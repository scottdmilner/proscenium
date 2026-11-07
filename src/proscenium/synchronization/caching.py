"""Caching time codes in a binding's published generation, without synchronizing (pipeline.md#cached-time-codes).

A cache call evaluates and plans the source at each time code the generation hasn't cached, under the generation's
settings, before changing any Blender data, so its source-state diagnostics exist before then, as a synchronization's
do. The application layer then keys the published display at them, and the generation record gains them. It
publishes no new generation, records no last attempt, and pushes no undo step, as Bindings pushes none for it.

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

from ..binding.persistence import binding_state, ledgers, manifests, records
from ..binding.results import Diagnostic, DiagnosticCode, Result
from ..binding.runtime import binding_configs, ownership
from ..binding.source_access import stages
from . import application, evaluation, prepared_work

if TYPE_CHECKING:
    from collections.abc import Collection

    from ..binding.persistence import configs
    from ..binding.runtime import stage_tracking
    from ..binding.source_access import identifiers


def cache(
    binding_id: identifiers.BindingId,
    config: configs.BindingConfig,
    current: stage_tracking.CurrentStages,
    time_codes: Collection[Usd.TimeCode],
) -> Result:
    """Cache the published generation's time-varying values at each of time_codes it hasn't cached, all or none.

    config is a usable binding's, and time_codes numeric. The result names the time codes it attempted, those the
    generation hadn't cached, in order. A generation synchronized at the default time code has nothing to cache, so
    the call succeeds caching nothing (CACHE-06); one with no generation, or whose source changed since it was
    synchronized, needs synchronizing, so the call fails caching nothing (CACHE-05).
    """
    scene, destination = config.scene, binding_configs.required_record(binding_id).collection
    assert scene is not None  # a binding's candidate names a target scene that exists
    manifest = manifests.read_manifest(destination)
    generation = binding_state.read_generation(destination)
    if isinstance(manifest, records.RefusedRecord):
        return Result(Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, manifest.message))
    if isinstance(generation, records.RefusedRecord):
        return Result(Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, generation.message))
    if generation is None:
        message = "The binding has no published generation to cache time codes in; synchronize it first"
        return Result(Diagnostic(DiagnosticCode.NEEDS_SYNCHRONIZATION, binding_id, message))
    published = generation.record
    if published.time_code is None:  # nothing in it varies with time
        return Result()
    have = {published.time_code, *published.cached_time_codes}
    new = sorted({t.GetValue() for t in time_codes} - have)
    attempted = [Usd.TimeCode(t) for t in new]
    if (refused := prepared_work.untrackable(binding_id)) is not None:
        return Result(refused, time_codes=attempted)

    binding_stages = current.attached(binding_id)
    try:
        evaluation_stage = binding_stages.acquire(published.payload_policy)
    except stages.SourceUnavailableError as error:
        return Result(Diagnostic(DiagnosticCode.NO_ATTACHED_STAGE, binding_id, str(error)), time_codes=attempted)
    # Checked even when every time code is cached, so a call never reports success over a source that changed. The
    # revision changes with anything evaluated: an edit, a reload that rereads a layer, an attachment, the evaluation
    # stage loaded to another payload policy since, or a new process.
    if binding_stages.source_revision != published.source_revision:
        message = "The source changed since the binding was synchronized; synchronize it before caching time codes"
        return Result(Diagnostic(DiagnosticCode.NEEDS_SYNCHRONIZATION, binding_id, message), time_codes=attempted)
    if not new:
        return Result()
    own = evaluation.source_state(binding_id, evaluation_stage)
    planned = evaluation.plans(binding_id, binding_stages, evaluation_stage, scene, attempted)
    if isinstance(planned, Diagnostic):
        return Result(*own, planned, time_codes=attempted)

    work = prepared_work.new_prepared_work(binding_id, ledgers.OriginatingOperation.CACHE)
    before = manifests.Manifest({}) if manifest is None else manifest.record
    try:
        changes = application.key_time_codes(dict(zip(new, planned, strict=True)), before, published.time_code, work)
    except Exception as error:  # noqa: BLE001 - any failure is the call's fatal diagnostic
        message = f"Keying the cached time codes failed: {error}"
        failed = Diagnostic(DiagnosticCode.PREPARATION_FAILED, binding_id, message)
        return Result(*own, failed, *_discarded(work), time_codes=attempted)
    cached = tuple(sorted({*published.cached_time_codes, *new}))
    try:
        # Restored whole, since an update by entry that fails partway may have written some entries.
        work.undo.append(functools.partial(manifests.write_manifest, destination, before))
        ownership.set_manifest_entries(binding_id, changes, created=work.datablocks, published=before)
        binding_state.write_generation(destination, dataclasses.replace(published, cached_time_codes=cached))
    except Exception as error:  # noqa: BLE001
        message = f"Recording the cached time codes failed: {error}"
        failed = Diagnostic(DiagnosticCode.PUBLICATION_FAILED, binding_id, message)
        return Result(*own, failed, *_discarded(work), time_codes=attempted)
    prepared_work.remove_staging(work)
    return Result(*own, time_codes=attempted)


def _discarded(work: prepared_work.PreparedWork) -> tuple[Diagnostic, ...]:
    """Undo work's changes to the published generation, and dispose of what it made; each disposal that failed.

    Raises, as defects, what reverting or writing the ledger raises, having disposed of the work either way.
    """
    try:
        prepared_work.revert(work)
    finally:
        disposed = prepared_work.dispose(work)
    return disposed
