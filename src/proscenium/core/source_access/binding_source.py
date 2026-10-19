"""A binding's source, and the stage the binding evaluates (source-access.md#source-stages)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pxr import Usd

if TYPE_CHECKING:
    from .sources import FileSource


class BindingSource:
    """A binding's source, and the evaluation stage it keeps and reuses across acquisitions.

    The source stage is the stage the source is composed on, which a file source opens itself.
    The evaluation stage composes the source stage's layers under the binding's own payload policy;
    when the binding opened the source stage, there are no caller's settings to protect, so the
    evaluation stage is the source stage. Layers are evaluated as loaded. Runtime state only.
    """

    source: FileSource
    payload_policy: Usd.Stage.InitialLoadSet  # requested; a change applies at the next acquisition
    _evaluation_stage: Usd.Stage | None
    _applied_payload_policy: Usd.Stage.InitialLoadSet  # the one the evaluation stage's load set follows

    def __init__(self, source: FileSource, payload_policy: Usd.Stage.InitialLoadSet) -> None:
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
        if self.source.stage is None:
            self._applied_payload_policy = self.payload_policy  # opened under it
        stage = self._evaluation_stage = self.source.open(self.payload_policy)
        self._apply_payload_policy(stage)
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
