"""Every binding's source, by binding identifier, and when each is made, kept, and let go.

Source stages, evaluation stages, and attachments are runtime state keyed by binding identity: they live in this
module, not in Blender data, so they are never saved in the .blend and undo neither restores nor
removes them (UNDO-06). A file source's path, and an attached source's key and root-layer identifier, are
binding configuration, which the binding's records keep (proscenium.persistence.bindings); attaching under a
source key reads them there. A source is made from its configuration on first use, and compared
with the bindings that exist whenever they may have changed (prune).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .binding_source import AttachedBindingSource, FileBindingSource
from .sources import AttachedSource, FileSource

if TYPE_CHECKING:
    from collections.abc import Collection


class SourceRegistry:
    """The sources of the process's bindings, by binding identifier."""

    _bindings: dict[str, FileBindingSource | AttachedBindingSource]

    def __init__(self) -> None:
        self._bindings = {}

    def file(self, binding_id: str, root: str | os.PathLike[str]) -> FileBindingSource:
        """The binding's file source on root, made if it has none; its source stage opens at the first acquisition.

        A source on another root is replaced, as when a "//" path resolves elsewhere after the .blend is
        saved elsewhere: the new file opens, and the old stage is let go.
        """
        found = self._bindings.get(binding_id)
        if isinstance(found, FileBindingSource) and found.source.root == os.fspath(root):
            return found
        source = self._bindings[binding_id] = FileBindingSource(FileSource(root))
        return source

    def attached(self, binding_id: str, key: str) -> AttachedBindingSource:
        """The binding's attached source, made unattached if it has none; an existing one keeps its attachment."""
        found = self._bindings.get(binding_id)
        if isinstance(found, AttachedBindingSource):
            return found
        source = self._bindings[binding_id] = AttachedBindingSource(AttachedSource(key))
        return source

    def get(self, binding_id: str) -> FileBindingSource | AttachedBindingSource | None:
        """The binding's source, or None before its first use."""
        return self._bindings.get(binding_id)

    def __contains__(self, binding_id: str) -> bool:
        return binding_id in self._bindings

    def __len__(self) -> int:
        return len(self._bindings)

    def release(self, key: str) -> None:
        """Release the stage attached under key from every source with that key, which leaves them unattached.

        Whether or not their binding still exists: one that doesn't keeps its attachment (prune).
        """
        for source in self._bindings.values():
            if isinstance(source, AttachedBindingSource) and source.source.key == key:
                source.release()

    def prune(self, existing: Collection[str], unreadable: Collection[str]) -> None:
        """Let go of the stages of sources whose binding no longer exists, or whose configuration can't be read.

        existing holds the identifiers of the bindings that exist, and unreadable those of them whose
        configuration can't be read. A file source's stage is dropped with its source; reopening it
        costs one open. An attached source keeps its attachment, since undo neither restores nor removes
        attachments (UNDO-06), so a binding redo brings back is still attached, and drops only its
        evaluation stage; release(key) still releases it. A binding whose configuration can't be read
        keeps its attachment and evaluation stage, as a binding that exists does.
        """
        for binding_id, source in list(self._bindings.items()):
            if isinstance(source, FileBindingSource):
                if binding_id not in existing or binding_id in unreadable:
                    del self._bindings[binding_id]
            elif binding_id not in existing:
                source.drop_evaluation_stage()
