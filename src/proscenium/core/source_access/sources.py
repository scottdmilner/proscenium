"""A binding's source: a file it opens, or a stage a caller attaches (source-access.md#source-identity)."""

from __future__ import annotations

import os

from pxr import Tf, Usd

from .._core import StageHandle


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

    The key and root-layer identifier are binding configuration, saved with the binding's records
    once they exist (M3 Phase D); until then they are held here. The attachment is runtime only.
    """

    key: str
    root_layer_identifier: str | None  # of the stage last attached; informative, never used to find bindings
    # Released at once, so it never keeps the attached stage alive (SRC-02). Unlike a weakref to the
    # Usd.Stage wrapper, which can return an expired wrapper, stage() is None once the stage expires.
    _attached: StageHandle | None

    def __init__(self, key: str, root_layer_identifier: str | None = None) -> None:
        self.key = key
        self.root_layer_identifier = root_layer_identifier
        self._attached = None

    @property
    def stage(self) -> Usd.Stage | None:
        """The attached stage while it exists."""
        return self._attached.stage() if self._attached is not None else None

    def attach(self, stage: Usd.Stage) -> None:
        """Make stage the source stage, and store its root-layer identifier."""
        handle = StageHandle(stage)
        handle.release()
        self._attached = handle
        self.root_layer_identifier = stage.GetRootLayer().identifier
