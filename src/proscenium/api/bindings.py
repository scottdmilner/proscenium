"""The process's bindings, and the handle callers reach one through (source-access.md#synchronization-api).

A synchronization runs the transaction (proscenium.synchronization) on a binding found usable, at the time code given
or else, as the transaction chooses it, the target scene's current frame's.
A cache call caches time codes in the published generation of a binding found usable, without synchronizing.

A binding's configuration is its records (proscenium.binding.persistence.binding_records). This module reaches them
through proscenium.binding.runtime.binding_operations, which reads and writes them when called. Its
stages and attachment are runtime state, never saved, in Bindings.stages (proscenium.binding.runtime.stage_tracking),
created unattached on first use.

A binding refuses the operations that need its configuration when the configuration can't be read
(lifecycle.md#schema-versions), or when the binding has copies and no canonical candidate, which disables it
pending repair (source-access.md#copied-bindings). Either way it keeps everything it has. A handle reaches a
binding's canonical candidate, and copied() reports the others.

A synchronization that publishes, and a cleanup retry that commits, push one undo step each, and nothing else does,
a cache call included;
none in background mode or with global undo off (lifecycle.md#undo-and-runtime-state). An operator calling the API
doesn't declare UNDO, so it adds no second step.

Each operation's result reports the binding's cleanup status as it ends (proscenium.binding.runtime.pending_cleanup),
a refusal's included.

Each kind of call reports a refusal one way:

- An operation (attach, synchronize, cache, set_settings, reload, retry_cleanup) returns a result whose diagnostic
  says why.
- The queries requested_settings and possibly_out_of_date raise RefusedRecordError for a configuration that can't be
  read, and DisabledBindingError for a disabled binding (FoundBinding.usable_config).
- A call needing records raises BindingNotFoundError for a binding that doesn't exist, which is misuse.
- While synchronize, cache, or retry_cleanup runs, a call to any of them, attach, release, or reload on any binding
  raises ReentrantCallError before changing anything, which is misuse too; set_settings may be called (CONS-04).
- Release clears runtime stages directly and remains valid after undo or removal.
- A failed write to the pending-cleanup ledger is a defect, and raises (pipeline.md#synchronization-transaction).
"""

from __future__ import annotations

import dataclasses
import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING

import bpy
from pxr import Usd

from ..binding.persistence import binding_state, id_property_records
from ..binding.results import Diagnostic, DiagnosticCode, Result, ResultState
from ..binding.runtime import binding_operations, pending_cleanup, stage_tracking
from ..binding.source_access import binding_settings, stages
from ..synchronization import cleanup_retry, time_code_caching, transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import Concatenate

    from ..binding.runtime import copy_detection
    from ..binding.source_access import binding_ids


# The types callers pass and receive, so callers outside proscenium import only this module: these, and Result,
# imported above.
RequestedSettings = binding_settings.RequestedSettings


def _reporting_cleanup[**P](
    operation: Callable[Concatenate[Bindings, binding_ids.BindingId, P], Result],
) -> Callable[Concatenate[Bindings, binding_ids.BindingId, P], Result]:
    """operation, its result reporting the binding's cleanup status once it ends."""

    @functools.wraps(operation)
    def reporting(bindings: Bindings, binding_id: binding_ids.BindingId, *args: P.args, **kwargs: P.kwargs) -> Result:
        result = operation(bindings, binding_id, *args, **kwargs)
        status = pending_cleanup.cleanup_status(binding_id)
        return Result(
            *result.diagnostics, attempted_time_codes=result.attempted_time_codes, pending_cleanup_diagnostics=status
        )

    return reporting


def _not_while_exclusive[**P, R](
    operation: Callable[Concatenate[Bindings, P], R],
) -> Callable[Concatenate[Bindings, P], R]:
    """operation, raising ReentrantCallError before it starts while an exclusive operation is running (CONS-04)."""

    @functools.wraps(operation)
    def checked(bindings: Bindings, *args: P.args, **kwargs: P.kwargs) -> R:
        if bindings.running:
            raise ReentrantCallError("Called while a synchronization, a cache call, or a cleanup retry is running")
        return operation(bindings, *args, **kwargs)

    return checked


def _exclusive[**P, R](operation: Callable[Concatenate[Bindings, P], R]) -> Callable[Concatenate[Bindings, P], R]:
    """operation, which no other exclusive operation, nor attach, release, or reload, runs during (CONS-04)."""

    @_not_while_exclusive
    @functools.wraps(operation)
    def exclusive(bindings: Bindings, *args: P.args, **kwargs: P.kwargs) -> R:
        bindings.running = True
        try:
            return operation(bindings, *args, **kwargs)
        finally:
            bindings.running = False

    return exclusive


class BindingNotFoundError(LookupError):  # misuse, raised like KeyError
    """No binding has this identifier: it was removed, its creation undone, or it never existed."""


class ReentrantCallError(RuntimeError):  # misuse
    """A call that can't run during a synchronization, a cache call, or a cleanup retry was made during one."""


@dataclass(frozen=True, slots=True)
class BindingHandle:
    """How callers reach a binding: its persistent identifier.

    Methods needing records look the binding up and raise BindingNotFoundError once it is gone.
    Release also works after removal or undo. Two handles are equal when their identifiers are.
    """

    binding_id: binding_ids.BindingId

    def attach(self, stage: Usd.Stage, *, confirm: bool = False) -> Result:
        """Attach a caller-owned stage to this binding, confirming a changed root identifier explicitly."""
        return BINDINGS.attach(self.binding_id, stage, confirm=confirm)

    def release(self) -> None:
        """Release this binding's source and evaluation stages, including after removal or undo."""
        BINDINGS.release(self.binding_id)

    def synchronize(self, time_code: Usd.TimeCode | float | None = None) -> Result:
        """Synchronize at time_code, or at the target scene's current frame's (Bindings.synchronize)."""
        return BINDINGS.synchronize(self.binding_id, time_code)

    def cache(self, time_codes: Iterable[Usd.TimeCode | float]) -> Result:
        """Cache the published generation at each of time_codes without synchronizing (Bindings.cache)."""
        return BINDINGS.cache(self.binding_id, time_codes)

    def set_settings(
        self,
        *,
        payload_policy: stages.PayloadPolicy | None = None,
        coordinate_conversion: bool | None = None,
        viewport_purposes: Iterable[str] | None = None,
        render_purposes: Iterable[str] | None = None,
    ) -> Result:
        """Record requested settings without synchronizing (Bindings.set_settings)."""
        return BINDINGS.set_settings(
            self.binding_id,
            payload_policy=payload_policy,
            coordinate_conversion=coordinate_conversion,
            viewport_purposes=viewport_purposes,
            render_purposes=render_purposes,
        )

    def reload(self, layers: Iterable[str] | None = None) -> Result:
        """Reread the binding's source layers on request (Bindings.reload)."""
        return BINDINGS.reload(self.binding_id, layers)

    def retry_cleanup(self) -> Result:
        """Retry the cleanup earlier attempts left pending (Bindings.retry_cleanup)."""
        return BINDINGS.retry_cleanup(self.binding_id)

    def possibly_out_of_date(self) -> bool:
        """Whether the display may not show the source as it is now (Bindings.possibly_out_of_date)."""
        return BINDINGS.possibly_out_of_date(self.binding_id)

    def requested_settings(self) -> RequestedSettings:
        """The settings the binding's next synchronization uses (Bindings.requested_settings)."""
        return BINDINGS.requested_settings(self.binding_id)

    def live_stage(self) -> Usd.Stage | None:
        """The binding's live stage, which callers inspect (Bindings.live_stage)."""
        return BINDINGS.live_stage(self.binding_id)


class Bindings:
    """The process's bindings: their records in Blender data, and their runtime stages."""

    stages: stage_tracking.BindingStageTracker  # never saved; cleared when a file is loaded (proscenium.addon)
    running: bool  # whether an exclusive operation, synchronize, cache, or retry_cleanup, is running
    published: dict[
        binding_ids.BindingId, binding_state.GenerationMetadata
    ]  # each binding's last this session (UNDO-05)

    def __init__(self) -> None:
        self.stages = stage_tracking.BindingStageTracker()
        self.running = False
        self.published = {}

    def create_binding(
        self,
        scene: bpy.types.Scene,
        *,
        payload_policy: stages.PayloadPolicy = stages.PayloadPolicy.LOAD_ALL,
        name: str = "USD Display",
    ) -> BindingHandle:
        """Create an unattached binding on scene with a new destination named name."""
        return BindingHandle(binding_operations.create(scene, binding_settings.new_settings(payload_policy), name))

    def in_scene(self, scene: bpy.types.Scene) -> list[BindingHandle]:
        """The bindings whose target scene is scene.

        Those whose canonical candidate names it, and each binding with copies and no canonical candidate that has a
        candidate naming it.
        """
        return [BindingHandle(found.binding_id) for found in binding_operations.find_bindings(scene)]

    def copied(self) -> list[copy_detection.CopiedBinding]:
        """Every binding identity that isn't unique: its candidates, which is canonical, and why, or none."""
        return binding_operations.copied_bindings()

    @_not_while_exclusive
    @_reporting_cleanup
    def attach(self, binding_id: binding_ids.BindingId, stage: Usd.Stage, *, confirm: bool = False) -> Result:
        """Attach stage to one binding, requiring confirmation when its stored root identifier differs."""
        found = self._require_binding(binding_id)
        if not found.usable:
            return _unusable_binding_result(found)
        config = found.usable_config()
        identifier = stage.GetRootLayer().identifier
        if config.root_layer_identifier not in (None, identifier) and not confirm:
            diagnostic = Diagnostic(
                DiagnosticCode.SOURCE_CONFIRMATION_REQUIRED,
                binding_id,
                "The attached stage has a different root-layer identifier; pass confirm=True to replace it",
            )
            return Result(diagnostic)
        binding_operations.set_config(binding_id, dataclasses.replace(config, root_layer_identifier=identifier))
        self.stages.get_or_create_binding_stages(binding_id).attach(stage)
        return Result()

    @_not_while_exclusive
    def release(self, binding_id: binding_ids.BindingId) -> None:
        """Release one binding's runtime stages; its persistent record need not exist."""
        self.stages.release(binding_id)

    def requested_settings(self, binding_id: binding_ids.BindingId) -> RequestedSettings:
        """The settings the binding's next synchronization uses.

        Raises RefusedRecordError if the binding's configuration can't be read, and DisabledBindingError if it has
        copies and no canonical candidate.
        """
        return self._require_binding(binding_id).usable_config().requested_settings

    @_reporting_cleanup
    def set_settings(
        self,
        binding_id: binding_ids.BindingId,
        *,
        payload_policy: stages.PayloadPolicy | None = None,
        coordinate_conversion: bool | None = None,
        viewport_purposes: Iterable[str] | None = None,
        render_purposes: Iterable[str] | None = None,
    ) -> Result:
        """Record requested settings without synchronizing; each one not given keeps its value.

        Raises ValueError or TypeError, changing nothing, for a value RequestedSettings refuses, such as a purpose USD
        doesn't define.
        """
        given = {
            "payload_policy": payload_policy,
            "coordinate_conversion": coordinate_conversion,
            "viewport_purposes": None if viewport_purposes is None else tuple(viewport_purposes),
            "render_purposes": None if render_purposes is None else tuple(render_purposes),
        }
        found = self._require_binding(binding_id)
        if not found.usable:
            return _unusable_binding_result(found)
        config = found.usable_config()
        settings = dataclasses.replace(config.requested_settings, **{k: v for k, v in given.items() if v is not None})
        binding_operations.set_config(binding_id, dataclasses.replace(config, requested_settings=settings))
        return Result()

    @_exclusive
    @_reporting_cleanup
    def synchronize(self, binding_id: binding_ids.BindingId, time_code: Usd.TimeCode | float | None = None) -> Result:
        """Synchronize through the transaction (proscenium.synchronization), at time_code if given.

        The result names the time code attempted; a refusal before the attempt names only one given.
        """
        given = None if time_code is None else Usd.TimeCode(time_code)  # one evaluation can use, or a TypeError now
        found = self._require_binding(binding_id)
        if not found.usable:
            return Result(
                *_unusable_binding_result(found).diagnostics, attempted_time_codes=() if given is None else (given,)
            )
        config = found.usable_config()
        result = transaction.synchronize(binding_id, config, self.stages, given)
        # Every failure before publication is fatal, and none after it (transaction.synchronize), so it published.
        if result.state is not ResultState.FATAL_FAILURE:
            assert found.destination is not None  # a usable binding's
            generation = binding_state.read_generation(found.destination)
            assert isinstance(generation, id_property_records.LoadedRecord)  # the one just published
            self.published[binding_id] = generation.record
            _push_undo("Synchronize USD Display")
        return result

    @_exclusive
    @_reporting_cleanup
    def cache(self, binding_id: binding_ids.BindingId, time_codes: Iterable[Usd.TimeCode | float]) -> Result:
        """Cache the published generation at each of time_codes not yet cached.

        See proscenium.synchronization.time_code_caching.

        One time code is a collection of one. The call publishes no generation, records no last attempt, and pushes no
        undo step (UNDO-09). The result names the time codes it attempted, those not cached before. Raises ValueError,
        caching nothing, for the default time code, which isn't one to cache.
        """
        given = [Usd.TimeCode(t) for t in time_codes]  # ones caching can use, or a TypeError now
        if any(t.IsDefault() for t in given):
            raise ValueError("The default time code isn't one to cache")
        found = self._require_binding(binding_id)
        if not found.usable:
            return _unusable_binding_result(found)
        return time_code_caching.cache(binding_id, found.usable_config(), self.stages, given)

    @_not_while_exclusive
    @_reporting_cleanup
    def reload(self, binding_id: binding_ids.BindingId, layers: Iterable[str] | None = None) -> Result:
        """Reread the binding's source layers on request, without synchronizing.

        Raises ValueError, and reloads nothing, if layers names one that isn't a contributing layer.
        """
        found = self._require_binding(binding_id)
        if not found.usable:
            return _unusable_binding_result(found)
        config = found.usable_config()
        try:
            self._get_or_create_stages(binding_id).reload(config.requested_settings.payload_policy, layers)
        except stages.SourceUnavailableError as error:
            return _source_unavailable_result(binding_id, error)
        return Result()

    @_exclusive
    @_reporting_cleanup
    def retry_cleanup(self, binding_id: binding_ids.BindingId) -> Result:
        """Retry the binding's pending cleanup, without USD access (proscenium.synchronization.cleanup_retry).

        Only this retries it, neither reopening the file nor a synchronization. Its result reports what's pending.
        """
        found = self._require_binding(binding_id)
        if not found.usable:
            return _unusable_binding_result(found)
        if pending_cleanup.nothing_pending(binding_id):
            return Result()  # nothing to retry, so nothing committed and no undo step
        result = cleanup_retry.retry_cleanup(binding_id)
        if result.state is not ResultState.FATAL_FAILURE:  # a retry resolving nothing, or unrecorded, is fatal
            _push_undo("Retry USD Display Cleanup")
        return result

    def possibly_out_of_date(self, binding_id: binding_ids.BindingId) -> bool:
        """Whether the binding's display may not show its source as it is now (lifecycle.md#undo-and-runtime-state).

        It's current only while it shows the generation this session last published for the binding, with any time codes
        cached in it since, and the source is still at that generation's revision. So an undo or redo that restores
        another generation makes it possibly out of date, as do a source change, a reload, an attachment, and
        reopening, until it synchronizes again. Raises as requested_settings does for a binding that isn't usable.
        """
        found = self._require_binding(binding_id)
        found.usable_config()  # raises for a binding that isn't usable
        published = self.published.get(binding_id)
        current = self.stages.get(binding_id)
        if published is None or current is None or found.destination is None:
            return True
        shown = binding_state.read_generation(found.destination)
        showing_it = isinstance(shown, id_property_records.LoadedRecord) and _without_cached_time_codes(
            shown.record
        ) == _without_cached_time_codes(published)
        return not showing_it or published.source_revision != current.source_revision

    def live_stage(self, binding_id: binding_ids.BindingId) -> Usd.Stage | None:
        """The caller's attached stage, or None when unattached or the configuration is unusable."""
        if not self._require_binding(binding_id).usable:
            return None
        return None if (stages := self.stages.get(binding_id)) is None else stages.live_stage

    def drop_all_stages(self) -> None:
        """Drop every binding's stages, leaving each with no source stage or attachment (BindingStageTracker.clear)."""
        self.stages.clear()

    def prune_stages(self) -> None:
        """Drop evaluation stages of bindings that no longer exist (BindingStageTracker.prune)."""
        self.stages.prune()

    def _require_binding(self, binding_id: binding_ids.BindingId) -> binding_operations.FoundBinding:
        """Find the binding or raise BindingNotFoundError if it doesn't exist."""
        if (found := binding_operations.find_binding(binding_id)) is None:
            raise BindingNotFoundError(binding_id)
        return found

    def _get_or_create_stages(self, binding_id: binding_ids.BindingId) -> stages.BindingStages:
        """The binding's stages, created unattached on first use."""
        return self.stages.get_or_create_binding_stages(binding_id)


def _undo_steps_enabled() -> bool:
    """Whether an operation that commits pushes an undo step: with global undo on, outside background mode (UNDO-04)."""
    preferences = bpy.context.preferences
    return not bpy.app.background and preferences is not None and preferences.edit.use_global_undo


def _push_undo(message: str) -> None:
    """Push the one undo step of an operation that committed, if steps are pushed (lifecycle.md#undo-and-runtime-state).

    An operator calling the API doesn't declare UNDO, so this is the only step (UNDO-02).
    """
    if _undo_steps_enabled():
        bpy.ops.ed.undo_push(message=message)


def _without_cached_time_codes(generation: binding_state.GenerationMetadata) -> binding_state.GenerationMetadata:
    """Copy the generation metadata with its cached time codes cleared."""
    return dataclasses.replace(generation, cached_time_codes=())


def _source_unavailable_result(binding_id: binding_ids.BindingId, error: stages.SourceUnavailableError) -> Result:
    """Build the failure result for a binding with no attached source stage."""
    return Result(Diagnostic(DiagnosticCode.NO_ATTACHED_STAGE, binding_id, str(error)))


def _unusable_binding_result(found: binding_operations.FoundBinding) -> Result:
    """Build the refusal result for an unreadable or ambiguously copied binding."""
    if found.configuration_refusal is not None:
        diagnostic = Diagnostic(
            DiagnosticCode.UNSUPPORTED_RECORD, found.binding_id, found.configuration_refusal.message
        )
        return Result(diagnostic)
    report = found.disabled_candidate_report
    assert report is not None
    named = ", ".join(
        f"{c.scene_name or 'no scene'}/{c.destination_name or 'no destination'}" for c in report.candidates
    )
    message = f"Binding {report.binding_id} has copies and no canonical candidate ({report.reason}): {named}"
    return Result(Diagnostic(DiagnosticCode.COPIED_BINDING, report.binding_id, message))


BINDINGS = Bindings()  # the process's bindings, which handles use
