"""The process's bindings, and the handle callers reach one through (source-access.md#synchronization-api).

A synchronization acquires the binding's evaluation stage under its requested settings and reports the source's
state; nothing is evaluated, planned, applied, or published yet.

A binding's configuration is its records (proscenium.persistence.binding_records), held and written through the
bindings' in-memory state (proscenium.runtime). Its stages and attachment are runtime state, never saved, in
Bindings.stages (proscenium.runtime.CurrentStages), made from the configuration on first use.

A binding refuses the operations that need its configuration when the configuration can't be read
(lifecycle.md#schema-versions), or when the binding has copies and no canonical candidate, which disables it
pending repair (source-access.md#copied-bindings). Either way it keeps everything it has. A handle reaches a
binding's canonical candidate, and copied() reports the others.

Each kind of call reports a refusal one way:

- An operation (synchronize, set_settings, reload) returns a result whose diagnostic says why.
- The query requested_settings raises RefusedRecordError for a configuration that can't be read, and
  DisabledBindingError for a disabled binding.
- A call keyed by binding identifier raises BindingNotFoundError for a binding that doesn't exist, which is misuse.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import bpy
from pxr import Usd

from .. import runtime
from ..core.results import Diagnostic, DiagnosticCategory, Result, ResultState, Severity
from ..core.source_access import (
    PayloadPolicy,
    SourceKind,
    SourceUnavailableError,
    dirty_layers,
)
from ..persistence.binding_records import BindingConfig
from ..persistence.records import RefusedRecord, RefusedRecordError
from ..runtime import CurrentStages, DisabledBinding, DisabledBindingError

if TYPE_CHECKING:
    import os
    from collections.abc import Iterable

    from ..core.binding_ids import BindingId
    from ..core.source_access import AttachedBindingStages, FileBindingStages
    from ..runtime.copy_detection import CopiedBinding


class BindingNotFoundError(LookupError):  # misuse, raised like KeyError
    """No binding has this identifier: it was removed, its creation undone, or it never existed."""


@dataclass(frozen=True, slots=True)
class RequestedSettings:
    """The settings a binding's next synchronization uses (lifecycle.md#binding-state)."""

    payload_policy: PayloadPolicy


@dataclass(frozen=True, slots=True)
class AttachResult:
    """What attach(key, stage) did: attached the stage, or refused.

    Refused when a binding with the key stored a different root-layer identifier and confirm wasn't passed:
    unconfirmed lists those bindings, and attached is empty. Otherwise unconfirmed is empty, and attached lists
    every binding the stage is now attached to: those with the key whose configuration can be read and isn't
    disabled, so none if no such binding has the key.
    """

    attached: tuple[BindingId, ...]  # the bindings the stage is now attached to
    unconfirmed: tuple[BindingId, ...]  # the bindings whose stored root-layer identifier differs from the stage's


@dataclass(frozen=True, slots=True)
class BindingHandle:
    """How callers reach a binding: its persistent identifier, never a datablock or cached state.

    Each method looks the binding up when it is called, and raises BindingNotFoundError once the
    binding is gone. Two handles are equal when their identifiers are.
    """

    binding_id: BindingId

    def synchronize(self, time_code: Usd.TimeCode | float) -> Result:
        """Synchronize at an explicit time code (Bindings.synchronize)."""
        return BINDINGS.synchronize(self.binding_id, time_code)

    def set_settings(self, *, payload_policy: PayloadPolicy | None = None) -> Result:
        """Record requested settings without synchronizing (Bindings.set_settings)."""
        return BINDINGS.set_settings(self.binding_id, payload_policy=payload_policy)

    def reload(self, layers: Iterable[str] | None = None) -> Result:
        """Reread the binding's source layers on request (Bindings.reload)."""
        return BINDINGS.reload(self.binding_id, layers)

    def requested_settings(self) -> RequestedSettings:
        """The settings the binding's next synchronization uses (Bindings.requested_settings)."""
        return BINDINGS.requested_settings(self.binding_id)

    def live_stage(self) -> Usd.Stage | None:
        """The binding's live stage, which callers inspect (Bindings.live_stage)."""
        return BINDINGS.live_stage(self.binding_id)


class Bindings:
    """The process's bindings: their records in Blender data, and their runtime stages."""

    stages: CurrentStages  # never saved; cleared when a file is loaded (proscenium.addon)

    def __init__(self) -> None:
        self.stages = CurrentStages()

    def create_file_binding(
        self,
        scene: bpy.types.Scene,
        root: str | os.PathLike[str],
        *,
        payload_policy: PayloadPolicy = PayloadPolicy.LOAD_ALL,
        name: str | None = None,
    ) -> BindingHandle:
        """A binding on scene whose source is the file root, with a new destination named name (or root's stem).

        A "//" path is relative to the .blend, so it raises ValueError in a file that was never saved.
        """
        if str(root).startswith("//") and not bpy.data.filepath:
            raise ValueError(f"{root} is relative to the .blend, which hasn't been saved")
        config = BindingConfig.file(str(root), payload_policy)
        return self._create(scene, config, name or Path(root).stem)

    def create_attached_binding(
        self,
        scene: bpy.types.Scene,
        key: str,
        *,
        payload_policy: PayloadPolicy = PayloadPolicy.LOAD_ALL,
        name: str | None = None,
    ) -> BindingHandle:
        """A binding on scene whose source a caller attaches under key, with a new destination named name (or key)."""
        config = BindingConfig.attached(key, payload_policy)
        return self._create(scene, config, name or key)

    def in_scene(self, scene: bpy.types.Scene) -> list[BindingHandle]:
        """The bindings whose target scene is scene.

        Those whose canonical candidate is on it, and each binding with copies and no canonical candidate that has a
        candidate on it.
        """
        return [BindingHandle(binding_id) for binding_id in runtime.binding_ids(scene)]

    def copied(self) -> list[CopiedBinding]:
        """Every binding identity that isn't unique: its candidates, which is canonical, and why, or none."""
        return runtime.copied_bindings()

    def attach(self, key: str, stage: Usd.Stage, *, confirm: bool = False) -> AttachResult:
        """Attach stage to every binding whose attached source has this exact key (source-access.md#source-identity).

        If any of them stored a root-layer identifier other than stage's, the caller must pass
        confirm=True; otherwise no binding changes, and the result lists those bindings. A binding
        whose configuration can't be read is never attached.
        """
        identifier = stage.GetRootLayer().identifier
        matching = list(runtime.attached_with_key(key))
        unconfirmed = tuple(
            binding_id for binding_id, config in matching if config.root_layer_identifier not in (None, identifier)
        )
        if unconfirmed and not confirm:
            return AttachResult(attached=(), unconfirmed=unconfirmed)  # before any change, so none is made

        for binding_id, config in matching:
            self.stages.attached(binding_id, key).attach(stage)
            runtime.set_config(binding_id, dataclasses.replace(config, root_layer_identifier=identifier))
        return AttachResult(attached=tuple(binding_id for binding_id, _ in matching), unconfirmed=())

    def release(self, key: str) -> tuple[BindingId, ...]:
        """Release the stage attached under key from every binding with that key, which leaves them unattached.

        The bindings hold an attached stage, and the layers it composes, until this, another attach,
        or a file load (source-access.md#source-stages). Returns the bindings with the key.
        """
        # Through the stages, not the bindings: a binding that no longer exists keeps its attachment (prune_stages()).
        self.stages.release(key)
        return tuple(binding_id for binding_id, _ in runtime.attached_with_key(key))

    def requested_settings(self, binding_id: BindingId) -> RequestedSettings:
        """The settings the binding's next synchronization uses.

        Raises RefusedRecordError if the binding's configuration can't be read, and DisabledBindingError if it has
        copies and no canonical candidate.
        """
        config = self._config(binding_id)
        if isinstance(config, RefusedRecord):
            raise RefusedRecordError(config)
        if isinstance(config, DisabledBinding):
            raise DisabledBindingError(config)
        return RequestedSettings(config.payload_policy)

    def set_settings(self, binding_id: BindingId, *, payload_policy: PayloadPolicy | None = None) -> Result:
        """Record requested settings without synchronizing."""
        config = self._config(binding_id)
        if not isinstance(config, BindingConfig):
            return _refused(config)
        if payload_policy is not None:
            config = dataclasses.replace(config, payload_policy=payload_policy)
        runtime.set_config(binding_id, config)
        return Result(ResultState.SUCCESS)

    def synchronize(self, binding_id: BindingId, time_code: Usd.TimeCode | float) -> Result:
        """Synchronize at an explicit time code; acquisition only, so nothing is evaluated at it yet."""
        Usd.TimeCode(time_code)  # a time code evaluation can use, or a TypeError now
        runtime.refresh_if_tags_changed()  # a collection duplicated on its own since the state was built is a copy
        config = self._config(binding_id)
        if not isinstance(config, BindingConfig):
            return _refused(config)
        if config.destination is None:  # removed: Blender cleared the pointer (lifecycle.md#removed-destination)
            return _removed_destination(binding_id)
        try:
            dirty = dirty_layers(self._stages(binding_id, config).acquire(config.payload_policy))
        except SourceUnavailableError as error:
            return _unavailable(error)
        diagnostics = ()
        if dirty:
            message = "Displaying layers with unsaved in-process edits"
            diagnostics = (Diagnostic(DiagnosticCategory.SOURCE_STATE, Severity.INFO, message, tuple(sorted(dirty))),)
        return Result(ResultState.SUCCESS, diagnostics)

    def reload(self, binding_id: BindingId, layers: Iterable[str] | None = None) -> Result:
        """Reread the binding's source layers on request, without synchronizing.

        Raises ValueError, and reloads nothing, if layers names one that isn't a contributing layer.
        """
        config = self._config(binding_id)
        if not isinstance(config, BindingConfig):
            return _refused(config)
        try:
            self._stages(binding_id, config).reload(config.payload_policy, layers)
        except SourceUnavailableError as error:
            return _unavailable(error)
        return Result(ResultState.SUCCESS)

    def live_stage(self, binding_id: BindingId) -> Usd.Stage | None:
        """None before the first synchronization, and for a binding with copies and no canonical candidate."""
        if isinstance(self._config(binding_id), DisabledBinding):
            return None
        return None if (stages := self.stages.get(binding_id)) is None else stages.live_stage

    def drop_all_stages(self) -> None:
        """Drop every binding's stages, leaving each with no source stage or attachment (CurrentStages.clear)."""
        self.stages.clear()

    def prune_stages(self) -> None:
        """Drop the stages of bindings that no longer exist or can't synchronize (CurrentStages.prune)."""
        self.stages.prune()

    def _create(self, scene: bpy.types.Scene, config: BindingConfig, name: str) -> BindingHandle:
        return BindingHandle(runtime.create(scene, config, name))

    def _config(self, binding_id: BindingId) -> BindingConfig | RefusedRecord | DisabledBinding:
        """The canonical candidate's configuration, why it can't be read, or DisabledBinding if it has none."""
        config = runtime.config(binding_id)
        if config is None:
            raise BindingNotFoundError(binding_id)
        return config

    def _stages(self, binding_id: BindingId, config: BindingConfig) -> FileBindingStages | AttachedBindingStages:
        """The binding's stages, made from its configuration on first use.

        A file source's path is resolved each time: a "//" path follows the .blend when it is saved
        elsewhere, and stages whose resolved file changed open the new one.
        """
        # BindingConfig checks that a file source has a path and an attached source a key.
        if config.source_kind is SourceKind.FILE:
            assert config.path is not None
            return self.stages.file(binding_id, bpy.path.abspath(config.path))
        assert config.source_key is not None
        return self.stages.attached(binding_id, config.source_key)


def _unavailable(error: SourceUnavailableError) -> Result:
    return Result(
        ResultState.FATAL_FAILURE, (Diagnostic(DiagnosticCategory.UNAVAILABLE_SOURCE, Severity.ERROR, str(error)),)
    )


def _removed_destination(binding_id: BindingId) -> Result:
    message = f"The destination collection of binding {binding_id} was removed"
    return Result(
        ResultState.FATAL_FAILURE, (Diagnostic(DiagnosticCategory.REMOVED_DESTINATION, Severity.ERROR, message),)
    )


def _refused(refused: RefusedRecord | DisabledBinding) -> Result:
    if isinstance(refused, RefusedRecord):
        return _unsupported(refused)
    report = refused.report
    named = ", ".join(f"{c.scene or 'no scene'}/{c.destination or 'no destination'}" for c in report.candidates)
    message = f"Binding {report.binding_id} has copies and no canonical candidate ({report.reason}): {named}"
    return Result(ResultState.FATAL_FAILURE, (Diagnostic(DiagnosticCategory.COPIED_BINDING, Severity.ERROR, message),))


def _unsupported(refused: RefusedRecord) -> Result:
    diagnostic = Diagnostic(DiagnosticCategory.UNSUPPORTED_RECORD, Severity.ERROR, refused.message)
    return Result(ResultState.FATAL_FAILURE, (diagnostic,))


BINDINGS = Bindings()  # the process's bindings, which handles use
