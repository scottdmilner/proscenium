"""A binding's stages: its source stage and the stage it evaluates (source-access.md#source-stages)."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pxr import Sdf, Usd

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


class PayloadPolicy(StrEnum):
    """A binding's payload policy: every payload loaded, or none (source-access.md#bindings-and-source-access).

    The one type for it, from the synchronization API to the binding's configuration, which stores
    its string value; USD's own Usd.Stage.InitialLoadSet appears only where a stage is opened.
    """

    LOAD_ALL = "load_all"
    LOAD_NONE = "load_none"

    @property
    def load_set(self) -> Usd.Stage.InitialLoadSet:
        """The initial load set to open a stage with."""
        return Usd.Stage.LoadAll if self is PayloadPolicy.LOAD_ALL else Usd.Stage.LoadNone


class SourceUnavailableError(Exception):
    """The binding has no attached source stage.

    Raised inside source access only; the synchronization API returns it as a result.
    """


def contributing_layers(stage: Usd.Stage) -> Iterator[Sdf.Layer]:
    """The non-anonymous layers the stage composes under its load set.

    A layer reached only through an unloaded payload doesn't contribute.
    """
    return (layer for layer in stage.GetUsedLayers() if not layer.anonymous)


def dirty_layers(stage: Usd.Stage) -> list[str]:
    """Identifiers of the stage's contributing layers with unsaved edits, for the source-state diagnostic."""
    return [layer.identifier for layer in contributing_layers(stage) if layer.dirty]


class BindingStages:
    """A binding's attached source stage and its own reused evaluation stage.

    The evaluation stage composes the source's root and session layers and matches its mask, muting,
    and interpolation at each acquisition. Its payload policy comes from the binding's configuration.
    The source is held until explicit release so its layers and unsaved edits have a clear lifetime.
    Layers are evaluated as loaded; only reload() rereads them.
    """

    _source_stage: Usd.Stage | None
    _evaluation_stage: Usd.Stage | None
    _payload_policy: PayloadPolicy | None  # the evaluation stage's: opened under it, or loaded or unloaded to it

    def __init__(self) -> None:
        self._source_stage = None
        self._evaluation_stage = None
        self._payload_policy = None

    @property
    def evaluation_stage(self) -> Usd.Stage | None:
        """The evaluation stage, or None before the first acquisition."""
        return self._evaluation_stage

    @property
    def live_stage(self) -> Usd.Stage | None:
        """The source stage, which callers inspect and browse (the binding's live stage)."""
        return self._source_stage

    def attach(self, stage: Usd.Stage) -> None:
        """Attach stage, letting go of an evaluation stage over another stage's layers."""
        self._source_stage = stage
        evaluation = self._evaluation_stage
        if evaluation is not None and (
            evaluation.GetRootLayer() != stage.GetRootLayer() or evaluation.GetSessionLayer() != stage.GetSessionLayer()
        ):
            self.drop_evaluation_stage()

    def drop_evaluation_stage(self) -> None:
        """Let go of the evaluation stage, keeping the attachment; the next acquisition reopens it."""
        self._evaluation_stage = None
        self._payload_policy = None

    def release(self) -> None:
        """Let go of the attached stage and the evaluation stage over its layers: the binding is unattached."""
        self._source_stage = None
        self.drop_evaluation_stage()

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
        """The reused evaluation stage matched to the source, opening one under payload_policy if needed."""
        attached = self._source_stage
        if attached is None:
            raise SourceUnavailableError("No stage is attached")
        stage = self._evaluation_stage
        if stage is None:
            # Inside an active cache context, Open can return the attached stage itself (runtime-record.md).
            with Usd.StageCacheContext(Usd.BlockStageCaches):
                stage = Usd.Stage.OpenMasked(
                    attached.GetRootLayer(),
                    attached.GetSessionLayer(),
                    attached.GetPathResolverContext(),
                    attached.GetPopulationMask(),
                    payload_policy.load_set,
                )
            self._evaluation_stage = stage
            self._payload_policy = payload_policy
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
