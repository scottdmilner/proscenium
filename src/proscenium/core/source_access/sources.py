"""A binding's source: a root-layer file it opens (source-access.md#source-identity)."""

from __future__ import annotations

import os

from pxr import Tf, Usd


class SourceUnavailable(Exception):  # noqa: N818 (an expected outcome, not an error)
    """The binding's source stage can't be had: its file won't open.

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
