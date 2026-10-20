"""A binding's source: a file it opens, or a stage a caller attaches (source-access.md#source-identity)."""

from __future__ import annotations

import os
from enum import StrEnum

from pxr import Tf, Usd

from .._core import StageHandle


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
    """A stage a caller attaches under a source key.

    The attachment is runtime only. The key, and the root-layer identifier of the stage last
    attached, are binding configuration, kept in the binding's records (proscenium.bindings).
    """

    key: str
    # Released at once, so it never keeps the attached stage alive (SRC-02). Unlike a weakref to the
    # Usd.Stage wrapper, which can return an expired wrapper, stage() is None once the stage expires.
    _attached: StageHandle | None

    def __init__(self, key: str) -> None:
        self.key = key
        self._attached = None

    @property
    def stage(self) -> Usd.Stage | None:
        """The attached stage while it exists."""
        return self._attached.stage() if self._attached is not None else None

    def attach(self, stage: Usd.Stage) -> None:
        """Make stage the source stage."""
        handle = StageHandle(stage)
        handle.release()
        self._attached = handle
