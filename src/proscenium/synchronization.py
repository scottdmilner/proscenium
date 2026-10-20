"""Synchronization keyed by binding identifier, behind the binding handle (source-access.md#synchronization-api).

M3 implements source acquisition: a synchronization acquires the binding's evaluation stage under
its requested settings and reports the source's state. Its time code is the attempt's, not a
setting of the binding. M5 adds evaluation at that time code, planning, application, and
publication, and the guard against reentrant calls.

A binding's configuration is its records (proscenium.bindings), read at every call; its source
stages and attachment are runtime state in a SourceRegistry, made from the configuration on first
use. A binding whose configuration can't be read keeps everything it has and refuses the
operations that need it, reporting why (lifecycle.md#schema-versions).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import bpy
from pxr import Usd

from . import bindings
from .bindings import BindingConfig, PayloadPolicy
from .core.source_access import AttachedSource, FileSource, SourceKind, SourceRegistry, SourceUnavailable
from .records import RecordRefused, Refused

if TYPE_CHECKING:
    import os
    from collections.abc import Iterable

    from .core.source_access import BindingSource


class BindingNotFound(LookupError):  # noqa: N818 (misuse, raised like KeyError)
    """No binding has this identifier: it was removed, its creation undone, or it never existed."""


class ResultState(StrEnum):
    SUCCESS = "success"
    COMPLETED_WITH_ISSUES = "completed with issues"
    FATAL_FAILURE = "fatal failure"


class Category(StrEnum):
    """Diagnostic categories source access reports (pipeline.md#diagnostics)."""

    UNAVAILABLE_SOURCE = "unavailable source"
    SOURCE_STATE = "source state"  # informational: it doesn't change the result state
    UNSUPPORTED_RECORD = "unsupported record"  # the binding's configuration can't be read


class Severity(StrEnum):
    INFO = "info"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    category: Category
    severity: Severity
    message: str
    layers: tuple[str, ...] = ()  # layer identifiers it concerns, sorted


@dataclass(frozen=True, slots=True)
class Result:
    """What an operation on a binding did. Expected failures are results, never exceptions."""

    state: ResultState
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class RequestedSettings:
    """The settings a binding's next synchronization uses (lifecycle.md#binding-state)."""

    payload_policy: Usd.Stage.InitialLoadSet


@dataclass(frozen=True, slots=True)
class AttachResult:
    """What attaching a stage under a source key did."""

    attached: tuple[str, ...]  # binding identifiers now evaluating the stage; empty if refused or none has the key
    unconfirmed: tuple[str, ...]  # bindings whose stored root-layer identifier differs; non-empty: nothing attached


@dataclass(frozen=True, slots=True)
class BindingHandle:
    """How callers reach a binding: its persistent identifier, never a datablock or cached state.

    Each method looks the binding up when it is called, and raises BindingNotFound once the
    binding is gone. Two handles are equal when their identifiers are.
    """

    binding_id: str

    def synchronize(self, time_code: Usd.TimeCode | float) -> Result:
        return SYNCHRONIZATION.synchronize(self.binding_id, time_code)

    def set_settings(self, *, payload_policy: Usd.Stage.InitialLoadSet | None = None) -> Result:
        return SYNCHRONIZATION.set_settings(self.binding_id, payload_policy=payload_policy)

    def reload(self, layers: Iterable[str] | None = None) -> Result:
        return SYNCHRONIZATION.reload(self.binding_id, layers)

    def requested_settings(self) -> RequestedSettings:
        return SYNCHRONIZATION.requested_settings(self.binding_id)

    def live_stage(self) -> Usd.Stage | None:
        return SYNCHRONIZATION.live_stage(self.binding_id)


class Synchronization:
    """The process's bindings: their records in Blender data, and their runtime sources."""

    sources: SourceRegistry  # runtime: dropped when a file is loaded (proscenium.addon)

    def __init__(self) -> None:
        self.sources = SourceRegistry()

    def create_file_binding(
        self,
        scene: bpy.types.Scene,
        root: str | os.PathLike[str],
        *,
        payload_policy: Usd.Stage.InitialLoadSet = Usd.Stage.LoadAll,
        name: str | None = None,
    ) -> BindingHandle:
        """A binding on scene whose source is the file root, with a new destination named name (or root's stem).

        A "//" path is relative to the .blend, so it raises ValueError in a file that was never saved.
        """
        if str(root).startswith("//") and not bpy.data.filepath:
            raise ValueError(f"{root} is relative to the .blend, which hasn't been saved")
        config = BindingConfig(SourceKind.FILE, str(root), None, None, None, PayloadPolicy.of(payload_policy))
        return BindingHandle(bindings.create(scene, config, name or Path(root).stem))

    def create_attached_binding(
        self,
        scene: bpy.types.Scene,
        key: str,
        *,
        payload_policy: Usd.Stage.InitialLoadSet = Usd.Stage.LoadAll,
        name: str | None = None,
    ) -> BindingHandle:
        """A binding on scene whose source a caller attaches under key, with a new destination named name (or key)."""
        config = BindingConfig(SourceKind.ATTACHED, None, key, None, None, PayloadPolicy.of(payload_policy))
        return BindingHandle(bindings.create(scene, config, name or key))

    def bindings(self, scene: bpy.types.Scene) -> list[BindingHandle]:
        """The bindings whose target scene is scene."""
        return [BindingHandle(binding_id) for binding_id in bindings.scene_bindings(scene)]

    def attach(self, key: str, stage: Usd.Stage, *, confirm: bool = False) -> AttachResult:
        """Attach stage to every binding whose attached source has this exact key (source-access.md#source-identity).

        If any of them stored a root-layer identifier other than stage's, the caller must pass
        confirm=True; otherwise no binding changes, and the result lists those bindings. A binding
        whose configuration can't be read is never attached.
        """
        identifier = stage.GetRootLayer().identifier
        matching = [
            (scene, binding_id, config.record)
            for scene, binding_id, config in bindings.all_bindings()
            if not isinstance(config, Refused)
            and config.record.source is SourceKind.ATTACHED
            and config.record.key == key
        ]
        unconfirmed = tuple(b for _, b, c in matching if c.root_layer_identifier not in (None, identifier))
        if unconfirmed and not confirm:
            return AttachResult(attached=(), unconfirmed=unconfirmed)
        for scene, binding_id, config in matching:
            source = self._source(binding_id, config).source
            assert isinstance(source, AttachedSource)
            source.attach(stage)
            bindings.update(scene, binding_id, dataclasses.replace(config, root_layer_identifier=identifier))
        return AttachResult(attached=tuple(b for _, b, _ in matching), unconfirmed=())

    def requested_settings(self, binding_id: str) -> RequestedSettings:
        """Raises RecordRefused if the binding's configuration can't be read."""
        config = self._config(binding_id)
        if isinstance(config, Refused):
            raise RecordRefused(config)
        return RequestedSettings(config.payload_policy.load_set)

    def set_settings(self, binding_id: str, *, payload_policy: Usd.Stage.InitialLoadSet | None = None) -> Result:
        """Record requested settings without synchronizing."""
        scene = self._scene(binding_id)
        config = self._config(binding_id)
        if isinstance(config, Refused):
            return _unsupported(config)
        if payload_policy is not None:
            config = dataclasses.replace(config, payload_policy=PayloadPolicy.of(payload_policy))
        bindings.update(scene, binding_id, config)
        return Result(ResultState.SUCCESS)

    def synchronize(self, binding_id: str, time_code: Usd.TimeCode | float) -> Result:
        """Synchronize at an explicit time code; acquisition only (M3), so nothing is evaluated at it yet."""
        Usd.TimeCode(time_code)  # a time code M5 can evaluate at, or a TypeError now
        config = self._config(binding_id)
        if isinstance(config, Refused):
            return _unsupported(config)
        source = self._source(binding_id, config)
        source.payload_policy = config.payload_policy.load_set
        try:
            dirty = source.dirty_layers()  # acquires the evaluation stage
        except SourceUnavailable as error:
            return _unavailable(error)
        diagnostics = ()
        if dirty:
            message = "Displaying layers with unsaved in-process edits"
            diagnostics = (Diagnostic(Category.SOURCE_STATE, Severity.INFO, message, tuple(sorted(dirty))),)
        return Result(ResultState.SUCCESS, diagnostics)

    def reload(self, binding_id: str, layers: Iterable[str] | None = None) -> Result:
        """Reread the binding's source layers on request, without synchronizing.

        Raises ValueError, and reloads nothing, if layers names one that isn't a contributing layer.
        """
        config = self._config(binding_id)
        if isinstance(config, Refused):
            return _unsupported(config)
        try:
            self._source(binding_id, config).reload(layers)
        except SourceUnavailable as error:
            return _unavailable(error)
        return Result(ResultState.SUCCESS)

    def live_stage(self, binding_id: str) -> Usd.Stage | None:
        self._scene(binding_id)
        return self.sources.get(binding_id).live_stage if binding_id in self.sources else None

    def file_loaded(self) -> None:
        """Drop every runtime source: a loaded file's bindings start with no source stage or attachment."""
        self.sources = SourceRegistry()

    def _scene(self, binding_id: str) -> bpy.types.Scene:
        if (found := bindings.find(binding_id)) is None:
            raise BindingNotFound(binding_id)
        return found[0]

    def _config(self, binding_id: str) -> BindingConfig | Refused:
        if (found := bindings.find(binding_id)) is None:
            raise BindingNotFound(binding_id)
        result = found[1]
        return result if isinstance(result, Refused) else result.record

    def _source(self, binding_id: str, config: BindingConfig) -> BindingSource:
        """The binding's runtime source, made from its configuration on first use.

        A file source's path is resolved each time: a "//" path follows the .blend when it is saved
        elsewhere, and a source whose resolved file changed opens the new one.
        """
        root = bpy.path.abspath(config.path) if config.source is SourceKind.FILE and config.path is not None else None
        if binding_id in self.sources:
            source = self.sources.get(binding_id)
            if not isinstance(source.source, FileSource) or source.source.root == root:
                return source
            self.sources.remove(binding_id)
        if root is not None:
            return self.sources.add_file(binding_id, root, config.payload_policy.load_set)
        assert config.key is not None
        return self.sources.add_attached(binding_id, config.key, config.payload_policy.load_set)


def _unavailable(error: SourceUnavailable) -> Result:
    return Result(ResultState.FATAL_FAILURE, (Diagnostic(Category.UNAVAILABLE_SOURCE, Severity.ERROR, str(error)),))


def _unsupported(refused: Refused) -> Result:
    diagnostic = Diagnostic(Category.UNSUPPORTED_RECORD, Severity.ERROR, refused.message)
    return Result(ResultState.FATAL_FAILURE, (diagnostic,))


SYNCHRONIZATION = Synchronization()  # the process's bindings, which handles use
