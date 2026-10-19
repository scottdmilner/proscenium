"""A binding's source, and the stage the binding evaluates (source-access.md#source-stages)."""

from __future__ import annotations

from pxr import Usd

from .sources import AttachedSource, FileSource, SourceUnavailable


class BindingSource:
    """A binding's source, and the evaluation stage it keeps and reuses across acquisitions.

    The source stage is the stage the source is composed on: the one a file source opens, or the
    one a caller attaches. The evaluation stage composes the source stage's root and session layers,
    matching its mask, muting, and interpolation, under the binding's own payload policy. When the
    binding opened the source stage itself, there are no caller's settings to protect, so the
    evaluation stage is the source stage. Layers are evaluated as loaded. Runtime state only.
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

    def _evaluation_stage_for(self, attached: Usd.Stage | None) -> Usd.Stage:
        """The evaluation stage for an attached stage: reused, or opened on its root and session layers."""
        if attached is None:
            # Let go of the attached stage's layers too, so they can be freed with it.
            self._evaluation_stage = None
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
