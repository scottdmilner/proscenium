"""Synchronization keyed by binding identifier, behind the binding handle (source-access.md#synchronization-api).

M3 implements source acquisition: a synchronization acquires the binding's evaluation stage under
its requested settings and reports the source's state. Its time code is the attempt's, not a
setting of the binding. M5 adds evaluation at that time code, planning, application, and
publication, and the guard against reentrant calls.

A binding's configuration is its records (proscenium.bindings), held and written through the
bindings' in-memory state (proscenium.indexes); its source stages and attachment are runtime state
in a SourceRegistry, made from the configuration on first use. A binding whose configuration can't
be read keeps everything it has and refuses the operations that need it, reporting why
(lifecycle.md#schema-versions).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import bpy
from pxr import Usd

from . import indexes
from .bindings import BindingConfig, PayloadPolicy
from .core.source_access import AttachedSource, FileSource, SourceKind, SourceRegistry, SourceUnavailable
from .records import RecordRefused, Refused
from .results import Category, Diagnostic, Result, ResultState, Severity

if TYPE_CHECKING:
    import os
    from collections.abc import Iterable

    from .core.source_access import BindingSource


class BindingNotFound(LookupError):  # noqa: N818 (misuse, raised like KeyError)
    """No binding has this identifier: it was removed, its creation undone, or it never existed."""


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
    _pruned_at: int | None  # indexes.rebuilds() when sources were last compared with the bindings

    def __init__(self) -> None:
        self.sources = SourceRegistry()
        self._pruned_at = None

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
        return self._create(scene, config, name or Path(root).stem)

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
        return self._create(scene, config, name or key)

    def bindings(self, scene: bpy.types.Scene) -> list[BindingHandle]:
        """The bindings whose target scene is scene."""
        return [BindingHandle(binding_id) for binding_id in indexes.binding_ids(scene)]

    def attach(self, key: str, stage: Usd.Stage, *, confirm: bool = False) -> AttachResult:
        """Attach stage to every binding whose attached source has this exact key (source-access.md#source-identity).

        If any of them stored a root-layer identifier other than stage's, the caller must pass
        confirm=True; otherwise no binding changes, and the result lists those bindings. A binding
        whose configuration can't be read is never attached.
        """
        identifier = stage.GetRootLayer().identifier
        matching = list(indexes.attached_with_key(key))
        unconfirmed = tuple(b for b, c in matching if c.root_layer_identifier not in (None, identifier))
        if unconfirmed and not confirm:
            return AttachResult(attached=(), unconfirmed=unconfirmed)
        for binding_id, config in matching:
            self._source(binding_id, config).attach(stage)
            indexes.set_config(binding_id, dataclasses.replace(config, root_layer_identifier=identifier))
        return AttachResult(attached=tuple(b for b, _ in matching), unconfirmed=())

    def release(self, key: str) -> tuple[str, ...]:
        """Release the stage attached under key from every binding with that key, which leaves them unattached.

        The bindings hold an attached stage, and the layers it composes, until this, another attach,
        or a file load (source-access.md#source-stages). Returns the bindings with the key.
        """
        self._prune_if_rebuilt()
        # Through the sources, not the bindings: a binding that no longer exists keeps its attachment (prune()).
        for _, source in self.sources.items():
            if isinstance(source.source, AttachedSource) and source.source.key == key:
                source.release()
        return tuple(binding_id for binding_id, _ in indexes.attached_with_key(key))

    def requested_settings(self, binding_id: str) -> RequestedSettings:
        """Raises RecordRefused if the binding's configuration can't be read."""
        config = self._config(binding_id)
        if isinstance(config, Refused):
            raise RecordRefused(config)
        return RequestedSettings(config.payload_policy.load_set)

    def set_settings(self, binding_id: str, *, payload_policy: Usd.Stage.InitialLoadSet | None = None) -> Result:
        """Record requested settings without synchronizing."""
        config = self._config(binding_id)
        if isinstance(config, Refused):
            return _unsupported(config)
        if payload_policy is not None:
            config = dataclasses.replace(config, payload_policy=PayloadPolicy.of(payload_policy))
        indexes.set_config(binding_id, config)
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
        self._pruned_at = None

    def prune(self) -> None:
        """Let go of the stages of sources whose binding no longer exists, or can't be read.

        A file source's stage is dropped with its source; reopening it costs one open. An attached
        source keeps its attachment, since undo neither restores nor removes attachments (UNDO-06), so
        a binding redo brings back is still attached, and drops only its evaluation stage; release(key)
        still releases it. A binding whose configuration can't be read keeps its attachment and
        evaluation stage, as a binding that exists does.
        """
        existing = set(indexes.binding_ids())
        for binding_id, source in self.sources.items():
            if binding_id in existing and not (
                isinstance(source.source, FileSource) and isinstance(indexes.config(binding_id), Refused)
            ):
                continue
            if isinstance(source.source, FileSource):
                self.sources.remove(binding_id)
            elif binding_id not in existing:
                source.drop_evaluation_stage()
        self._pruned_at = indexes.rebuilds()

    def _prune_if_rebuilt(self) -> None:
        if self._pruned_at != indexes.rebuilds():
            self.prune()

    def _create(self, scene: bpy.types.Scene, config: BindingConfig, name: str) -> BindingHandle:
        return BindingHandle(indexes.create(scene, config, name))

    # Every per-binding call goes through _scene or _config, and every use of a source through _source,
    # so each compares the sources with the bindings when the bindings' state was rebuilt.

    def _scene(self, binding_id: str) -> bpy.types.Scene:
        self._prune_if_rebuilt()
        if (scene := indexes.binding_scene(binding_id)) is None:
            raise BindingNotFound(binding_id)
        return scene

    def _config(self, binding_id: str) -> BindingConfig | Refused:
        self._prune_if_rebuilt()
        if (config := indexes.config(binding_id)) is None:
            raise BindingNotFound(binding_id)
        return config

    def _source(self, binding_id: str, config: BindingConfig) -> BindingSource:
        """The binding's runtime source, made from its configuration on first use.

        A file source's path is resolved each time: a "//" path follows the .blend when it is saved
        elsewhere, and a source whose resolved file changed opens the new one.
        """
        self._prune_if_rebuilt()
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
