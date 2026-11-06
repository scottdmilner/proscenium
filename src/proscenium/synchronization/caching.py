"""Caching time codes in a binding's published generation, without synchronizing (pipeline.md#cached-time-codes).

A cache call evaluates and plans the source at each time code the generation hasn't cached, under the generation's
settings, before changing any Blender data, so its source-state diagnostics exist before then, as a synchronization's
do. The application layer then keys the published display at them, and the generation record gains them. It
publishes no new generation, records no last attempt, and pushes no undo step, as Bindings pushes none for it.
"""

from __future__ import annotations

import dataclasses
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
    generation hadn't cached, in order.
    """
    scene, destination = config.scene, binding_configs.required_record(binding_id).collection
    assert scene is not None  # a binding's candidate names a target scene that exists
    manifest = manifests.read_manifest(destination)
    generation = binding_state.read_generation(destination)
    if isinstance(manifest, records.RefusedRecord):
        return Result(Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, manifest.message))
    if isinstance(generation, records.RefusedRecord):
        return Result(Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, binding_id, generation.message))
    assert manifest is not None and generation is not None  # E3 refuses a binding with nothing published
    published = generation.record
    assert published.time_code is not None  # E3: one at the default time code has nothing to cache
    have = {published.time_code, *published.cached_time_codes}
    new = sorted({t.GetValue() for t in time_codes} - have)
    attempted = [Usd.TimeCode(t) for t in new]
    if not new:
        return Result()

    binding_stages = current.attached(binding_id)
    try:
        evaluation_stage = binding_stages.acquire(published.payload_policy)
    except stages.SourceUnavailableError as error:
        return Result(Diagnostic(DiagnosticCode.NO_ATTACHED_STAGE, binding_id, str(error)), time_codes=attempted)
    own = evaluation.source_state(binding_id, evaluation_stage)
    planned = evaluation.plans(binding_id, binding_stages, evaluation_stage, scene, attempted)
    if isinstance(planned, Diagnostic):
        return Result(*own, planned, time_codes=attempted)

    work = prepared_work.new_prepared_work(binding_id, ledgers.OriginatingOperation.CACHE)
    changes = application.key_time_codes(
        dict(zip(new, planned, strict=True)), manifest.record, published.time_code, work
    )
    ownership.set_manifest_entries(binding_id, changes, created=work.datablocks)
    cached = tuple(sorted({*published.cached_time_codes, *new}))
    binding_state.write_generation(destination, dataclasses.replace(published, cached_time_codes=cached))
    prepared_work.remove_staging(work)
    return Result(*own, time_codes=attempted)
