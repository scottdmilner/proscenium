"""A binding's source, and the stage the binding evaluates (source-access.md#source-stages)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pxr import Sdf, Usd

from .sources import AttachedSource, FileSource, SourceUnavailable

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


def contributing_layers(stage: Usd.Stage) -> Iterator[Sdf.Layer]:
    """The non-anonymous layers the stage composes under its load set.

    A layer reached only through an unloaded payload doesn't contribute.
    """
    return (layer for layer in stage.GetUsedLayers() if not layer.anonymous)


class BindingSource:
    """A binding's source, and the evaluation stage it keeps and reuses across acquisitions.

    The source stage is the stage the source is composed on: the one a file source opens, or the
    one a caller attaches. The evaluation stage composes the source stage's root and session layers,
    matching its mask, muting, and interpolation, under the binding's own payload policy. When the
    binding opened the source stage itself, there are no caller's settings to protect, so the
    evaluation stage is the source stage. Layers are evaluated as loaded; only reload() rereads them.
    Runtime state only.
    """

    source: FileSource | AttachedSource
    payload_policy: Usd.Stage.InitialLoadSet  # requested; a change applies at the next acquisition
    _evaluation_stage: Usd.Stage | None
    _applied_payload_policy: Usd.Stage.InitialLoadSet  # the one the evaluation stage's load set follows

    def __init__(self, source: FileSource | AttachedSource, payload_policy: Usd.Stage.InitialLoadSet) -> None:
        self.source = source
        self.payload_policy = payload_policy
        self._evaluation_stage = None
        self._applied_payload_policy = payload_policy

    @property
    def evaluation_stage(self) -> Usd.Stage | None:
        """The evaluation stage, or None before the first acquisition."""
        return self._evaluation_stage

    @property
    def live_stage(self) -> Usd.Stage | None:
        """The source stage, which callers inspect and browse (the binding's live stage)."""
        return self.source.stage

    def acquire(self) -> Usd.Stage:
        """The evaluation stage, matched to the source stage. Raises SourceUnavailable."""
        if isinstance(self.source, FileSource):
            if self.source.stage is None:
                self._applied_payload_policy = self.payload_policy  # opened under it
            stage = self._evaluation_stage = self.source.open(self.payload_policy)
        else:
            stage = self._evaluation_stage_for(self.source.stage)
        self._apply_payload_policy(stage)
        return stage

    def attach(self, stage: Usd.Stage) -> None:
        """Attach stage to an attached source, letting go of an evaluation stage over another stage's layers."""
        assert isinstance(self.source, AttachedSource)
        self.source.attach(stage)
        evaluation = self._evaluation_stage
        if evaluation is not None and (
            evaluation.GetRootLayer() != stage.GetRootLayer() or evaluation.GetSessionLayer() != stage.GetSessionLayer()
        ):
            self._evaluation_stage = None

    def drop_evaluation_stage(self) -> None:
        """Let go of an attached source's evaluation stage, keeping the attachment; the next acquisition reopens it."""
        assert isinstance(self.source, AttachedSource)
        self._evaluation_stage = None

    def release(self) -> None:
        """Let go of an attached source's stage and the evaluation stage over its layers: the binding is unattached."""
        if isinstance(self.source, AttachedSource):
            self.source.release()
            self._evaluation_stage = None

    def dirty_layers(self) -> list[str]:
        """Identifiers of the contributing layers with unsaved edits, for the source-state diagnostic."""
        return [layer.identifier for layer in contributing_layers(self.acquire()) if layer.dirty]

    def reload(self, layers: Iterable[str] | None = None) -> None:
        """Reread contributing layers from disk, discarding the unsaved edits of dirty ones.

        With layers, only those identifiers, each of which must be a contributing layer; otherwise
        ValueError, and nothing is reloaded. Non-forced, so an unchanged clean layer stays as it is,
        without notices; on Windows that misses a rewrite within the same second, as in USD itself.
        Raises SourceUnavailable.
        """
        stage = self.acquire()
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

    def _evaluation_stage_for(self, attached: Usd.Stage | None) -> Usd.Stage:
        """The evaluation stage for an attached stage: reused, or opened on its root and session layers."""
        if attached is None:
            raise SourceUnavailable("No stage is attached")
        stage = self._evaluation_stage
        if (
            stage is None
            or stage.GetRootLayer() != attached.GetRootLayer()
            or stage.GetSessionLayer() != attached.GetSessionLayer()
        ):
            # Inside an active cache context, Open can return the attached stage itself (runtime-record.md).
            with Usd.StageCacheContext(Usd.BlockStageCaches):
                stage = self._evaluation_stage = Usd.Stage.OpenMasked(
                    attached.GetRootLayer(),
                    attached.GetSessionLayer(),
                    attached.GetPathResolverContext(),
                    attached.GetPopulationMask(),
                    self.payload_policy,
                )
            self._applied_payload_policy = self.payload_policy
        elif stage.GetPopulationMask() != attached.GetPopulationMask():
            # Reused: the caller may have changed its mask since the last acquisition.
            stage.SetPopulationMask(attached.GetPopulationMask())
        # Settings stored in no layer, matched at every acquisition. The mask is set above, since
        # OpenMasked takes it; muting and interpolation are matched here for new and reused stages.
        muted, wanted = set(stage.GetMutedLayers()), set(attached.GetMutedLayers())
        if muted != wanted:
            stage.MuteAndUnmuteLayers(sorted(wanted - muted), sorted(muted - wanted))
        stage.SetInterpolationType(attached.GetInterpolationType())
        return stage

    def _apply_payload_policy(self, stage: Usd.Stage) -> None:
        """Load or unload every payload on the reused stage to match a changed payload policy."""
        if self._applied_payload_policy == self.payload_policy:
            return
        if self.payload_policy == Usd.Stage.LoadAll:
            stage.Load()
        else:
            stage.Unload()
        self._applied_payload_policy = self.payload_policy
