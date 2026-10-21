"""A binding's source: a file it opens, or a stage a caller attaches (source-access.md#source-identity)."""

from __future__ import annotations

import os
from enum import StrEnum

from pxr import Tf, Usd


class SourceKind(StrEnum):
    """The two kinds of source a binding has: a FileSource or an AttachedSource."""

    FILE = "file"
    ATTACHED = "attached"


class SourceUnavailable(Exception):  # noqa: N818 (an expected outcome, not an error)
    """The binding's source stage can't be had: its file won't open, or no stage is attached.

    Raised inside source access only; the synchronization API returns it as a result.
    """


class FileSource:
    """A root-layer file, whose source stage the binding opens itself and reuses.

    The stage is opened outside every stage cache and never placed in one, so no other binding
    or tool can be handed it. It starts with an empty session layer and is never saved.
    """

    root: str
    _stage: Usd.Stage | None

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = os.fspath(root)
        self._stage = None

    @property
    def stage(self) -> Usd.Stage | None:
        """The source stage, or None before the first acquisition."""
        return self._stage

    def open(self, payload_policy: Usd.Stage.InitialLoadSet) -> Usd.Stage:
        """The source stage, opening it under payload_policy if it isn't open. Raises SourceUnavailable."""
        if self._stage is None:
            try:
                # Inside an active cache context, a plain Open can return another tool's cached stage.
                with Usd.StageCacheContext(Usd.BlockStageCaches):
                    self._stage = Usd.Stage.Open(self.root, payload_policy)
            except Tf.ErrorException as error:
                raise SourceUnavailable(f"Can't open {self.root}") from error
        return self._stage


class AttachedSource:
    """A stage a caller attaches under a source key, held until the caller releases it (SRC-02).

    The binding's evaluation stage composes the attached stage's layers, so it keeps them alive in any
    case, and USD sends no notice when a stage is destroyed: a binding that let go of a stage the
    caller dropped would still hold its layers, unsaved edits included, until it next looked. So the
    attachment holds the stage itself, and release() is the caller's way to free it.

    The attachment is runtime only. The key, and the root-layer identifier of the stage last
    attached, are binding configuration, kept in the binding's records (proscenium.bindings).
    """

    key: str
    _stage: Usd.Stage | None

    def __init__(self, key: str) -> None:
        self.key = key
        self._stage = None

    @property
    def stage(self) -> Usd.Stage | None:
        """The attached stage, or None if none is attached."""
        return self._stage

    def attach(self, stage: Usd.Stage) -> None:
        """Make stage the source stage, releasing any stage attached before."""
        self._stage = stage

    def release(self) -> None:
        self._stage = None
