"""The process's bindings, and the handle callers reach one through (source-access.md#synchronization-api).

A synchronization runs the transaction (proscenium.synchronization) on a binding found usable; so far it acquires the
binding's evaluation stage under its requested settings and reports the source's state.

A binding's configuration is its records (proscenium.binding.persistence.configs), which this module reaches only
through the bindings' in-memory state (proscenium.binding.runtime.binding_configs), which holds and writes them. Its
stages and attachment are runtime state, never saved, in Bindings.stages (proscenium.binding.runtime.stage_tracking),
created unattached on first use.

A binding refuses the operations that need its configuration when the configuration can't be read
(lifecycle.md#schema-versions), or when the binding has copies and no canonical candidate, which disables it
pending repair (source-access.md#copied-bindings). Either way it keeps everything it has. A handle reaches a
binding's canonical candidate, and copied() reports the others.

Each operation's result reports the binding's cleanup status as it ends (proscenium.binding.runtime.pending_cleanup),
a refusal's included.

Each kind of call reports a refusal one way:

- An operation (attach, synchronize, set_settings, reload, retry_cleanup) returns a result whose diagnostic says why.
- The query requested_settings raises RefusedRecordError for a configuration that can't be read, and
  DisabledBindingError for a disabled binding (FoundBinding.usable_config).
- A call needing records raises BindingNotFoundError for a binding that doesn't exist, which is misuse.
- Release clears runtime stages directly and remains valid after undo or removal.
"""

from __future__ import annotations

import dataclasses
import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pxr import Usd

from ..binding.results import Diagnostic, DiagnosticCode, Result
from ..binding.runtime import binding_configs, pending_cleanup, stage_tracking, state
from ..binding.source_access import binding_settings, stages
from ..synchronization import cleanup_retry, transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import Concatenate

    import bpy

    from ..binding.runtime import copy_detection
    from ..binding.source_access import identifiers


# The types callers pass and receive, so callers outside proscenium import only this module: these, and Result,
# imported above.
RequestedSettings = binding_settings.RequestedSettings


def _reporting_cleanup[**P](
    operation: Callable[Concatenate[Bindings, identifiers.BindingId, P], Result],
) -> Callable[Concatenate[Bindings, identifiers.BindingId, P], Result]:
    """operation, its result reporting the binding's cleanup status once it ends."""

    @functools.wraps(operation)
    def reporting(bindings: Bindings, binding_id: identifiers.BindingId, *args: P.args, **kwargs: P.kwargs) -> Result:
        result = operation(bindings, binding_id, *args, **kwargs)
        status = pending_cleanup.cleanup_status(binding_id)
        return Result(*result.diagnostics, time_codes=result.time_codes, cleanup_status=status)

    return reporting


class BindingNotFoundError(LookupError):  # misuse, raised like KeyError
    """No binding has this identifier: it was removed, its creation undone, or it never existed."""


@dataclass(frozen=True, slots=True)
class BindingHandle:
    """How callers reach a binding: its persistent identifier.

    Methods needing records look the binding up and raise BindingNotFoundError once it is gone.
    Release also works after removal or undo. Two handles are equal when their identifiers are.
    """

    binding_id: identifiers.BindingId

    def attach(self, stage: Usd.Stage, *, confirm: bool = False) -> Result:
        """Attach a caller-owned stage to this binding, confirming a changed root identifier explicitly."""
        return BINDINGS.attach(self.binding_id, stage, confirm=confirm)

    def release(self) -> None:
        """Release this binding's source and evaluation stages, including after removal or undo."""
        BINDINGS.release(self.binding_id)

    def synchronize(self, time_code: Usd.TimeCode | float) -> Result:
        """Synchronize at an explicit time code (Bindings.synchronize)."""
        return BINDINGS.synchronize(self.binding_id, time_code)

    def set_settings(self, *, payload_policy: stages.PayloadPolicy | None = None) -> Result:
        """Record requested settings without synchronizing (Bindings.set_settings)."""
        return BINDINGS.set_settings(self.binding_id, payload_policy=payload_policy)

    def reload(self, layers: Iterable[str] | None = None) -> Result:
        """Reread the binding's source layers on request (Bindings.reload)."""
        return BINDINGS.reload(self.binding_id, layers)

    def retry_cleanup(self) -> Result:
        """Retry the cleanup earlier attempts left pending (Bindings.retry_cleanup)."""
        return BINDINGS.retry_cleanup(self.binding_id)

    def requested_settings(self) -> RequestedSettings:
        """The settings the binding's next synchronization uses (Bindings.requested_settings)."""
        return BINDINGS.requested_settings(self.binding_id)

    def live_stage(self) -> Usd.Stage | None:
        """The binding's live stage, which callers inspect (Bindings.live_stage)."""
        return BINDINGS.live_stage(self.binding_id)


class Bindings:
    """The process's bindings: their records in Blender data, and their runtime stages."""

    stages: stage_tracking.CurrentStages  # never saved; cleared when a file is loaded (proscenium.addon)

    def __init__(self) -> None:
        self.stages = stage_tracking.CurrentStages()

    def create_binding(
        self,
        scene: bpy.types.Scene,
        *,
        payload_policy: stages.PayloadPolicy = stages.PayloadPolicy.LOAD_ALL,
        name: str = "USD Display",
    ) -> BindingHandle:
        """Create an unattached binding on scene with a new destination named name."""
        return BindingHandle(binding_configs.create(scene, RequestedSettings(payload_policy), name))

    def in_scene(self, scene: bpy.types.Scene) -> list[BindingHandle]:
        """The bindings whose target scene is scene.

        Those whose canonical candidate is on it, and each binding with copies and no canonical candidate that has a
        candidate on it.
        """
        return [BindingHandle(found.binding_id) for found in binding_configs.find_bindings(scene)]

    def copied(self) -> list[copy_detection.CopiedBinding]:
        """Every binding identity that isn't unique: its candidates, which is canonical, and why, or none."""
        return binding_configs.copied_bindings()

    @_reporting_cleanup
    def attach(self, binding_id: identifiers.BindingId, stage: Usd.Stage, *, confirm: bool = False) -> Result:
        """Attach stage to one binding, requiring confirmation when its stored root identifier differs."""
        found = self._found(binding_id)
        if not found.usable:
            return _refused(found)
        config = found.usable_config()
        identifier = stage.GetRootLayer().identifier
        if config.root_layer_identifier not in (None, identifier) and not confirm:
            diagnostic = Diagnostic(
                DiagnosticCode.SOURCE_CONFIRMATION_REQUIRED,
                binding_id,
                "The attached stage has a different root-layer identifier; pass confirm=True to replace it",
            )
            return Result(diagnostic)
        binding_configs.set_config(binding_id, dataclasses.replace(config, root_layer_identifier=identifier))
        self.stages.attached(binding_id).attach(stage)
        return Result()

    def release(self, binding_id: identifiers.BindingId) -> None:
        """Release one binding's runtime stages; its persistent record need not exist."""
        self.stages.release(binding_id)

    def requested_settings(self, binding_id: identifiers.BindingId) -> RequestedSettings:
        """The settings the binding's next synchronization uses.

        Raises RefusedRecordError if the binding's configuration can't be read, and DisabledBindingError if it has
        copies and no canonical candidate.
        """
        return self._found(binding_id).usable_config().settings

    @_reporting_cleanup
    def set_settings(
        self, binding_id: identifiers.BindingId, *, payload_policy: stages.PayloadPolicy | None = None
    ) -> Result:
        """Record requested settings without synchronizing."""
        found = self._found(binding_id)
        if not found.usable:
            return _refused(found)
        config = found.usable_config()
        if payload_policy is not None:
            settings = dataclasses.replace(config.settings, payload_policy=payload_policy)
            config = dataclasses.replace(config, settings=settings)
        binding_configs.set_config(binding_id, config)
        return Result()

    @_reporting_cleanup
    def synchronize(self, binding_id: identifiers.BindingId, time_code: Usd.TimeCode | float) -> Result:
        """Synchronize at an explicit time code through the transaction (proscenium.synchronization).

        The result names the time code, whatever it reports, a refusal's included.
        """
        attempted = Usd.TimeCode(time_code)  # a time code evaluation can use, or a TypeError now
        state.refresh_if_tags_changed()  # a collection duplicated on its own since the state was built is a copy
        found = self._found(binding_id)
        if not found.usable:
            return Result(*_refused(found).diagnostics, time_codes=(attempted,))
        return transaction.synchronize(binding_id, found.usable_config(), self.stages, attempted)

    @_reporting_cleanup
    def reload(self, binding_id: identifiers.BindingId, layers: Iterable[str] | None = None) -> Result:
        """Reread the binding's source layers on request, without synchronizing.

        Raises ValueError, and reloads nothing, if layers names one that isn't a contributing layer.
        """
        found = self._found(binding_id)
        if not found.usable:
            return _refused(found)
        config = found.usable_config()
        try:
            self._stages(binding_id).reload(config.settings.payload_policy, layers)
        except stages.SourceUnavailableError as error:
            return _unavailable(binding_id, error)
        return Result()

    @_reporting_cleanup
    def retry_cleanup(self, binding_id: identifiers.BindingId) -> Result:
        """Retry the binding's pending cleanup, without USD access (proscenium.synchronization.cleanup_retry).

        Only this retries it, neither reopening the file nor a synchronization. Its result reports what's pending.
        """
        found = self._found(binding_id)
        if not found.usable:
            return _refused(found)
        return cleanup_retry.retry_cleanup(binding_id)

    def live_stage(self, binding_id: identifiers.BindingId) -> Usd.Stage | None:
        """The caller's attached stage, or None when unattached or the configuration is unusable."""
        if not self._found(binding_id).usable:
            return None
        return None if (stages := self.stages.get(binding_id)) is None else stages.live_stage

    def drop_all_stages(self) -> None:
        """Drop every binding's stages, leaving each with no source stage or attachment (CurrentStages.clear)."""
        self.stages.clear()

    def prune_stages(self) -> None:
        """Drop evaluation stages of bindings that no longer exist (CurrentStages.prune)."""
        self.stages.prune()

    def _found(self, binding_id: identifiers.BindingId) -> binding_configs.FoundBinding:
        """The binding; raises BindingNotFoundError if it doesn't exist."""
        if (found := binding_configs.find_binding(binding_id)) is None:
            raise BindingNotFoundError(binding_id)
        return found

    def _stages(self, binding_id: identifiers.BindingId) -> stages.BindingStages:
        """The binding's stages, created unattached on first use."""
        return self.stages.attached(binding_id)


def _unavailable(binding_id: identifiers.BindingId, error: stages.SourceUnavailableError) -> Result:
    return Result(Diagnostic(DiagnosticCode.NO_ATTACHED_STAGE, binding_id, str(error)))


def _refused(found: binding_configs.FoundBinding) -> Result:
    """Why a binding that isn't usable refuses."""
    if found.unreadable is not None:
        diagnostic = Diagnostic(DiagnosticCode.UNSUPPORTED_RECORD, found.binding_id, found.unreadable.message)
        return Result(diagnostic)
    report = found.copies
    assert report is not None
    named = ", ".join(f"{c.scene or 'no scene'}/{c.destination or 'no destination'}" for c in report.candidates)
    message = f"Binding {report.binding_id} has copies and no canonical candidate ({report.reason}): {named}"
    return Result(Diagnostic(DiagnosticCode.COPIED_BINDING, report.binding_id, message))


BINDINGS = Bindings()  # the process's bindings, which handles use
