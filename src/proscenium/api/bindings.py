"""The process's bindings, and the handle callers reach one through (source-access.md#synchronization-api).

M3 implements source acquisition: a synchronization acquires the binding's evaluation stage under
its requested settings and reports the source's state. Its time code is the attempt's, not a
setting of the binding. M5 adds evaluation at that time code, planning, application, and
publication, and the guard against reentrant calls.

A binding's configuration is its records (proscenium.persistence.binding_records), held and written through the
bindings' in-memory state (proscenium.runtime); its stages and attachment are runtime state
in a StageRegistry, made from the configuration on first use. A binding whose configuration can't
be read keeps everything it has and refuses the operations that need it, reporting why
(lifecycle.md#schema-versions). So does a binding with copies and no canonical candidate, which is
disabled pending repair; a handle reaches a binding's canonical candidate, and copied() reports the
others (source-access.md#copied-bindings).

A refusal is reported one way for each kind of call. An operation (synchronize, set_settings, reload)
returns a result whose diagnostic says why. The query requested_settings raises: RefusedRecordError
for a configuration that can't be read, and BindingDisabledError for a disabled binding. Every call keyed
by binding identifier raises BindingNotFoundError for a binding that doesn't exist, which is misuse.
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
    StageRegistry,
    dirty_layers,
)
from ..persistence.binding_records import BindingConfig
from ..persistence.records import RefusedRecord, RefusedRecordError
from ..runtime import BindingDisabledError
from ..runtime.copy_detection import CopiedBinding

if TYPE_CHECKING:
    import os
    from collections.abc import Iterable

    from ..core.source_access import AttachedBindingStages, FileBindingStages


class BindingNotFoundError(LookupError):  # misuse, raised like KeyError
    """No binding has this identifier: it was removed, its creation undone, or it never existed."""


@dataclass(frozen=True, slots=True)
class RequestedSettings:
    """The settings a binding's next synchronization uses (lifecycle.md#binding-state)."""

    payload_policy: PayloadPolicy


@dataclass(frozen=True, slots=True)
class AttachResult:
    """What attaching a stage under a source key did."""

    attached: tuple[str, ...]  # binding identifiers now evaluating the stage; empty if refused or none has the key
    unconfirmed: tuple[str, ...]  # bindings whose stored root-layer identifier differs; non-empty: nothing attached


@dataclass(frozen=True, slots=True)
class BindingHandle:
    """How callers reach a binding: its persistent identifier, never a datablock or cached state.

    Each method looks the binding up when it is called, and raises BindingNotFoundError once the
    binding is gone. Two handles are equal when their identifiers are.
    """

    binding_id: str

    def synchronize(self, time_code: Usd.TimeCode | float) -> Result:
        return BINDINGS.synchronize(self.binding_id, time_code)

    def set_settings(self, *, payload_policy: PayloadPolicy | None = None) -> Result:
        return BINDINGS.set_settings(self.binding_id, payload_policy=payload_policy)

    def reload(self, layers: Iterable[str] | None = None) -> Result:
        return BINDINGS.reload(self.binding_id, layers)

    def requested_settings(self) -> RequestedSettings:
        return BINDINGS.requested_settings(self.binding_id)

    def live_stage(self) -> Usd.Stage | None:
        return BINDINGS.live_stage(self.binding_id)


class Bindings:
    """The process's bindings: their records in Blender data, and their runtime stages."""

    stages: StageRegistry  # runtime: dropped when a file is loaded (proscenium.addon)
    _pruned_at: int | None  # runtime.rebuild_count() when the stages were last compared with the bindings

    def __init__(self) -> None:
        self.stages = StageRegistry()
        self._pruned_at = None

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
        config = BindingConfig(SourceKind.FILE, str(root), None, None, None, payload_policy)
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
        config = BindingConfig(SourceKind.ATTACHED, None, key, None, None, payload_policy)
        return self._create(scene, config, name or key)

    def in_scene(self, scene: bpy.types.Scene) -> list[BindingHandle]:
        """The bindings whose target scene is scene: whose canonical candidate is on it, or, for a binding with
        copies and no canonical candidate, which has a candidate on it."""
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
        unconfirmed = tuple(b for b, c in matching if c.root_layer_identifier not in (None, identifier))
        if unconfirmed and not confirm:
            return AttachResult(attached=(), unconfirmed=unconfirmed)
        self._prune_if_rebuilt()
        for binding_id, config in matching:
            self.stages.attached(binding_id, key).attach(stage)
            runtime.set_config(binding_id, dataclasses.replace(config, root_layer_identifier=identifier))
        return AttachResult(attached=tuple(b for b, _ in matching), unconfirmed=())

    def release(self, key: str) -> tuple[str, ...]:
        """Release the stage attached under key from every binding with that key, which leaves them unattached.

        The bindings hold an attached stage, and the layers it composes, until this, another attach,
        or a file load (source-access.md#source-stages). Returns the bindings with the key.
        """
        self._prune_if_rebuilt()
        # Through the stages, not the bindings: a binding that no longer exists keeps its attachment (prune_stages()).
        self.stages.release(key)
        return tuple(binding_id for binding_id, _ in runtime.attached_with_key(key))

    def requested_settings(self, binding_id: str) -> RequestedSettings:
        """Raises RefusedRecordError if the binding's configuration can't be read, and BindingDisabledError if it has
        copies and no canonical candidate."""
        config = self._config(binding_id)
        if isinstance(config, RefusedRecord):
            raise RefusedRecordError(config)
        if isinstance(config, CopiedBinding):
            raise BindingDisabledError(config)
        return RequestedSettings(config.payload_policy)

    def set_settings(self, binding_id: str, *, payload_policy: PayloadPolicy | None = None) -> Result:
        """Record requested settings without synchronizing."""
        config = self._config(binding_id)
        if not isinstance(config, BindingConfig):
            return _refused(config)
        if payload_policy is not None:
            config = dataclasses.replace(config, payload_policy=payload_policy)
        runtime.set_config(binding_id, config)
        return Result(ResultState.SUCCESS)

    def synchronize(self, binding_id: str, time_code: Usd.TimeCode | float) -> Result:
        """Synchronize at an explicit time code; acquisition only (M3), so nothing is evaluated at it yet."""
        Usd.TimeCode(time_code)  # a time code M5 can evaluate at, or a TypeError now
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

    def reload(self, binding_id: str, layers: Iterable[str] | None = None) -> Result:
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

    def live_stage(self, binding_id: str) -> Usd.Stage | None:
        """None before the first synchronization, and for a binding with copies and no canonical candidate."""
        if isinstance(self._config(binding_id), CopiedBinding):
            return None
        return None if (stages := self.stages.get(binding_id)) is None else stages.live_stage

    def on_file_loaded(self) -> None:
        """Drop every binding's stages: a loaded file's bindings start with no source stage or attachment."""
        self.stages = StageRegistry()
        self._pruned_at = None

    def prune_stages(self) -> None:
        """Let go of the stages of bindings that no longer exist, or can't synchronize (StageRegistry.prune).

        With no stages, as before a session's first synchronization, there's nothing to compare, so the
        bindings' state isn't rebuilt for it, in the undo and redo handler or anywhere else.
        """
        if self.stages:
            configs = runtime.configs()
            # A disabled binding's file source goes, as an unreadable one's does: neither synchronizes.
            self.stages.prune(configs.keys(), {b for b, c in configs.items() if not isinstance(c, BindingConfig)})
        self._pruned_at = runtime.rebuild_count()

    def _prune_if_rebuilt(self) -> None:
        if self._pruned_at != runtime.rebuild_count():
            self.prune_stages()

    def _create(self, scene: bpy.types.Scene, config: BindingConfig, name: str) -> BindingHandle:
        return BindingHandle(runtime.create(scene, config, name))

    # Every per-binding call goes through _config, and every use of a binding's stages through _stages,
    # except attach and release, which reach stages by key and call _prune_if_rebuilt themselves; so each
    # compares the stages with the bindings when the bindings' state was rebuilt. A new entry point that
    # uses a binding's stages does one or the other, and this comment names it.

    def _config(self, binding_id: str) -> BindingConfig | RefusedRecord | CopiedBinding:
        """The canonical candidate's configuration, why it can't be read, or, with none, the binding's candidates."""
        self._prune_if_rebuilt()
        config = runtime.config(binding_id)
        if config is None:
            raise BindingNotFoundError(binding_id)
        return config

    def _stages(self, binding_id: str, config: BindingConfig) -> FileBindingStages | AttachedBindingStages:
        """The binding's stages, made from its configuration on first use.

        A file source's path is resolved each time: a "//" path follows the .blend when it is saved
        elsewhere, and stages whose resolved file changed open the new one.
        """
        self._prune_if_rebuilt()
        if config.source is SourceKind.FILE:
            assert config.path is not None
            return self.stages.file(binding_id, bpy.path.abspath(config.path))
        assert config.key is not None
        return self.stages.attached(binding_id, config.key)


def _unavailable(error: SourceUnavailableError) -> Result:
    return Result(
        ResultState.FATAL_FAILURE, (Diagnostic(DiagnosticCategory.UNAVAILABLE_SOURCE, Severity.ERROR, str(error)),)
    )


def _removed_destination(binding_id: str) -> Result:
    message = f"The destination collection of binding {binding_id} was removed"
    return Result(
        ResultState.FATAL_FAILURE, (Diagnostic(DiagnosticCategory.REMOVED_DESTINATION, Severity.ERROR, message),)
    )


def _refused(refused: RefusedRecord | CopiedBinding) -> Result:
    if isinstance(refused, RefusedRecord):
        return _unsupported(refused)
    named = ", ".join(f"{c.scene or 'no scene'}/{c.destination or 'no destination'}" for c in refused.candidates)
    message = f"Binding {refused.binding_id} has copies and no canonical candidate ({refused.reason}): {named}"
    return Result(ResultState.FATAL_FAILURE, (Diagnostic(DiagnosticCategory.COPIED_BINDING, Severity.ERROR, message),))


def _unsupported(refused: RefusedRecord) -> Result:
    diagnostic = Diagnostic(DiagnosticCategory.UNSUPPORTED_RECORD, Severity.ERROR, refused.message)
    return Result(ResultState.FATAL_FAILURE, (diagnostic,))


BINDINGS = Bindings()  # the process's bindings, which handles use
