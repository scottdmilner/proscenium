"""A binding's stages: its source stage and the stage it evaluates (source-access.md#source-stages)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, NamedTuple, override

from pxr import Sdf, Usd

from .sources import AttachedSource, FileSource, PayloadPolicy, SourceUnavailableError

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


def contributing_layers(stage: Usd.Stage) -> Iterator[Sdf.Layer]:
    """The non-anonymous layers the stage composes under its load set.

    A layer reached only through an unloaded payload doesn't contribute.
    """
    return (layer for layer in stage.GetUsedLayers() if not layer.anonymous)


def dirty_layers(stage: Usd.Stage) -> list[str]:
    """Identifiers of the stage's contributing layers with unsaved edits, for the source-state diagnostic."""
    return [layer.identifier for layer in contributing_layers(stage) if layer.dirty]


class MatchedStage(NamedTuple):
    """An evaluation stage matched to the source stage, and whether it was just opened."""

    stage: Usd.Stage
    opened: bool  # opened under the payload policy asked for, rather than reused


class BindingStages[S: (FileSource, AttachedSource)](ABC):
    """A binding's stages: the source stage its source is composed on, and the evaluation stage it synchronizes.

    - The source stage is the one a file source opens, or the one a caller attaches.
    - The evaluation stage is kept and reused, and matched to the source stage at each acquisition: it composes the
      source stage's root and session layers under the source stage's mask, muting, and interpolation, which no layer
      stores. Only its payload policy is the binding's own, passed at each acquisition from its configuration.
    - A file source's stage is the binding's own, with no caller's settings to protect, so it is also the evaluation
      stage.

    Layers are evaluated as loaded; only reload() rereads them. One subclass for each kind of source.
    """

    source: S
    _evaluation_stage: Usd.Stage | None
    _payload_policy: PayloadPolicy | None  # the evaluation stage's: opened under it, or loaded or unloaded to it

    def __init__(self, source: S) -> None:
        self.source = source
        self._evaluation_stage = None
        self._payload_policy = None

    @property
    def evaluation_stage(self) -> Usd.Stage | None:
        """The evaluation stage, or None before the first acquisition."""
        return self._evaluation_stage

    @property
    def live_stage(self) -> Usd.Stage | None:
        """The source stage, which callers inspect and browse (the binding's live stage)."""
        return self.source.stage

    def acquire(self, payload_policy: PayloadPolicy) -> Usd.Stage:
        """The evaluation stage, matched to the source stage, its payloads loaded or unloaded to payload_policy.

        Raises SourceUnavailableError.
        """
        stage = self._current_evaluation_stage(payload_policy)
        if self._payload_policy != payload_policy:
            # A reused stage: never reopened, so the session layer's opinions stay.
            if payload_policy is PayloadPolicy.LOAD_ALL:
                stage.Load()
            else:
                stage.Unload()
            self._payload_policy = payload_policy
        return stage

    def reload(self, payload_policy: PayloadPolicy, layers: Iterable[str] | None = None) -> None:
        """Reread contributing layers from disk, discarding the unsaved edits of dirty ones.

        The contributing layers are the evaluation stage's under the payload policy it has, which a
        reload leaves alone, since it doesn't synchronize; payload_policy opens one only if there is none.
        With layers, only those identifiers, each of which must be a contributing layer; otherwise
        ValueError, and nothing is reloaded. Non-forced, so an unchanged clean layer stays as it is,
        without notices; on Windows that misses a rewrite within the same second, as in USD itself.
        Raises SourceUnavailableError.
        """
        stage = self._current_evaluation_stage(payload_policy)
        if layers is not None:
            by_identifier = {layer.identifier: layer for layer in contributing_layers(stage)}
            unknown = sorted(set(layers) - by_identifier.keys())
            if unknown:
                raise ValueError(f"Not contributing layers of the binding: {', '.join(unknown)}")
            Sdf.Layer.ReloadLayers({by_identifier[identifier] for identifier in layers})
            return
        # A reload that changes composition can bring in a stale layer another tool holds.
        reloaded: set[Sdf.Layer] = set()
        while pending := set(contributing_layers(stage)) - reloaded:
            Sdf.Layer.ReloadLayers(pending)
            reloaded |= pending

    def _current_evaluation_stage(self, payload_policy: PayloadPolicy) -> Usd.Stage:
        """The evaluation stage, matched to the source stage and kept; one just opened is under payload_policy."""
        stage, opened = self._match_evaluation_stage(payload_policy)
        self._evaluation_stage = stage
        if opened:
            self._payload_policy = payload_policy
        return stage

    @abstractmethod
    def _match_evaluation_stage(self, payload_policy: PayloadPolicy) -> MatchedStage:
        """The evaluation stage matched to the source stage: the one held, or one opened under payload_policy.

        Raises SourceUnavailableError.
        """


class FileBindingStages(BindingStages[FileSource]):
    """A binding on a file: its evaluation stage is the source stage it opens itself."""

    @override
    def _match_evaluation_stage(self, payload_policy: PayloadPolicy) -> MatchedStage:
        opened = self.source.stage is None
        return MatchedStage(self.source.open(payload_policy), opened)


class AttachedBindingStages(BindingStages[AttachedSource]):
    """A binding on a stage a caller attaches: its evaluation stage composes that stage's layers."""

    def attach(self, stage: Usd.Stage) -> None:
        """Attach stage, letting go of an evaluation stage over another stage's layers."""
        self.source.attach(stage)
        evaluation = self._evaluation_stage
        if evaluation is not None and (
            evaluation.GetRootLayer() != stage.GetRootLayer() or evaluation.GetSessionLayer() != stage.GetSessionLayer()
        ):
            self._evaluation_stage = None

    def drop_evaluation_stage(self) -> None:
        """Let go of the evaluation stage, keeping the attachment; the next acquisition reopens it."""
        self._evaluation_stage = None

    def release(self) -> None:
        """Let go of the attached stage and the evaluation stage over its layers: the binding is unattached."""
        self.source.release()
        self._evaluation_stage = None

    @override
    def _match_evaluation_stage(self, payload_policy: PayloadPolicy) -> MatchedStage:
        """Reused, or opened on the attached stage's root and session layers."""
        attached = self.source.stage
        if attached is None:
            raise SourceUnavailableError("No stage is attached")
        stage = self._evaluation_stage
        opened = (
            stage is None
            or stage.GetRootLayer() != attached.GetRootLayer()
            or stage.GetSessionLayer() != attached.GetSessionLayer()
        )
        if opened:
            # Inside an active cache context, Open can return the attached stage itself (runtime-record.md).
            with Usd.StageCacheContext(Usd.BlockStageCaches):
                stage = Usd.Stage.OpenMasked(
                    attached.GetRootLayer(),
                    attached.GetSessionLayer(),
                    attached.GetPathResolverContext(),
                    attached.GetPopulationMask(),
                    payload_policy.load_set,
                )
        elif stage.GetPopulationMask() != attached.GetPopulationMask():
            # Reused: the caller may have changed its mask since the last acquisition.
            stage.SetPopulationMask(attached.GetPopulationMask())
        # Settings stored in no layer, matched at every acquisition. The mask is set above, since
        # OpenMasked takes it; muting and interpolation are matched here for new and reused stages.
        muted, wanted = set(stage.GetMutedLayers()), set(attached.GetMutedLayers())
        if muted != wanted:
            stage.MuteAndUnmuteLayers(sorted(wanted - muted), sorted(muted - wanted))
        stage.SetInterpolationType(attached.GetInterpolationType())
        return MatchedStage(stage, opened)
