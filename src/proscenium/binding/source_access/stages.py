"""A binding's stages: its source stage and the stage it evaluates (source-access.md#source-stages)."""

from __future__ import annotations

import itertools
import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING, NewType

from pxr import Sdf, Tf, Usd

from . import binding_settings

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Iterator

# What a binding's evaluated source was at some moment: equal revisions mean nothing it evaluates changed between
# them. Unique in the process and to it, so a generation synchronized in another session never matches one.
SourceRevision = NewType("SourceRevision", str)

_PROCESS = uuid.uuid4().hex
_revision_numbers = itertools.count(1)


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


class _SourceRevisions:
    """A binding's current source revision, which its evaluation stage's listener advances."""

    current: SourceRevision

    def __init__(self) -> None:
        self.advance()

    def advance(self) -> None:
        self.current = SourceRevision(f"{_PROCESS}.{next(_revision_numbers)}")


class BindingStages:
    """A binding's attached source stage and its own reused evaluation stage.

    The evaluation stage composes the source's root and session layers and matches its mask, muting,
    and interpolation at each acquisition. Its payload policy comes from the binding's configuration.
    The source is held until explicit release so its layers and unsaved edits have a clear lifetime.
    Layers are evaluated as loaded; only reload() rereads them.

    The source revision changes with anything the evaluation stage evaluates: an edit to one of its layers, a
    reload that rereads one, a caller's setting or a payload policy that an acquisition matches, and every
    attachment and new evaluation stage. An acquisition that matches nothing new leaves it.
    """

    _source_stage: Usd.Stage | None
    _evaluation_stage: Usd.Stage | None
    # The evaluation stage's policy: opened under it, or loaded or unloaded to it.
    _payload_policy: binding_settings.PayloadPolicy | None
    _revisions: _SourceRevisions
    # Advances the revision on the evaluation stage's ObjectsChanged; it holds the revisions, not self, so it keeps
    # nothing else alive, and is revoked when dropped.
    _listener: Tf.Notice.Listener | None

    def __init__(self) -> None:
        self._source_stage = None
        self._evaluation_stage = None
        self._payload_policy = None
        self._revisions = _SourceRevisions()
        self._listener = None

    @property
    def evaluation_stage(self) -> Usd.Stage | None:
        """The evaluation stage, or None before the first acquisition."""
        return self._evaluation_stage

    @property
    def live_stage(self) -> Usd.Stage | None:
        """The source stage, which callers inspect and browse (the binding's live stage)."""
        return self._source_stage

    @property
    def source_revision(self) -> SourceRevision:
        """What the evaluated source is now, for a generation to be compared with (pipeline.md#cached-time-codes)."""
        return self._revisions.current

    @contextmanager
    def monitor_evaluation_layer_changes(self) -> Generator[set[str]]:
        """Monitor evaluation layers within this context, yielding the set of identifiers that change.

        For a diagnostic naming the layers that changed during an evaluation (source-access.md#source-consistency).
        The layers are those the stage composes on entry, its anonymous session layer included. Raises
        SourceUnavailableError before the first acquisition.
        """
        stage = self._evaluation_stage
        if stage is None:
            raise SourceUnavailableError("No stage is evaluated")
        used = set(stage.GetUsedLayers())
        changed: set[str] = set()

        def gather(notice: Sdf.Notice.LayersDidChange, _sender: object) -> None:
            changed.update(layer.identifier for layer in notice.GetLayers() if layer in used)

        listener = Tf.Notice.RegisterGlobally(Sdf.Notice.LayersDidChange, gather)
        try:
            yield changed
        finally:
            listener.Revoke()

    def attach(self, stage: Usd.Stage) -> None:
        """Attach stage, letting go of an evaluation stage over another stage's layers; the revision changes."""
        self._source_stage = stage
        self._revisions.advance()
        evaluation = self._evaluation_stage
        if evaluation is not None and (
            evaluation.GetRootLayer() != stage.GetRootLayer() or evaluation.GetSessionLayer() != stage.GetSessionLayer()
        ):
            self.drop_evaluation_stage()

    def drop_evaluation_stage(self) -> None:
        """Let go of the evaluation stage, keeping the attachment; the next acquisition reopens it."""
        if self._listener is not None:
            self._listener.Revoke()
        self._listener = None
        self._evaluation_stage = None
        self._payload_policy = None
        self._revisions.advance()

    def release(self) -> None:
        """Let go of the attached stage and the evaluation stage over its layers: the binding is unattached."""
        self._source_stage = None
        self.drop_evaluation_stage()

    def acquire_evaluation_stage(self, payload_policy: binding_settings.PayloadPolicy) -> Usd.Stage:
        """Acquire the evaluation stage, matching source settings and applying payload_policy.

        Raises SourceUnavailableError.
        """
        stage = self._ensure_evaluation_stage_matches_source(payload_policy)
        if self._payload_policy != payload_policy:
            # A reused stage: never reopened, so the session layer's opinions stay.
            if payload_policy is binding_settings.PayloadPolicy.LOAD_ALL:
                stage.Load()
            else:
                stage.Unload()
            self._payload_policy = payload_policy
        return stage

    def reload(self, payload_policy: binding_settings.PayloadPolicy, layers: Iterable[str] | None = None) -> None:
        """Reread contributing layers from disk, discarding the unsaved edits of dirty ones.

        The contributing layers are the evaluation stage's under the payload policy it has, which a
        reload leaves alone, since it doesn't synchronize; payload_policy opens one only if there is none.
        With layers, only those identifiers, each of which must be a contributing layer; otherwise
        ValueError, and nothing is reloaded. Non-forced, so an unchanged clean layer stays as it is,
        without notices; on Windows that misses a rewrite within the same second, as in USD itself.
        Raises SourceUnavailableError.
        """
        stage = self._ensure_evaluation_stage_matches_source(payload_policy)
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

    def _ensure_evaluation_stage_matches_source(self, payload_policy: binding_settings.PayloadPolicy) -> Usd.Stage:
        """Open or reuse the evaluation stage and match the source's mask, muting, and interpolation."""
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
            revisions = self._revisions
            self._listener = Tf.Notice.Register(Usd.Notice.ObjectsChanged, lambda *_: revisions.advance(), stage)
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
