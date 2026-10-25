"""Every binding's stages, by binding identifier: when each is made, kept, and let go.

- Source stages, evaluation stages, and attachments are runtime state, not Blender data: they are never saved in the
  .blend, and undo neither restores nor removes them (UNDO-06).
- What they are made from is configuration, kept in the binding's records (proscenium.persistence.binding_records):
  a file source's path, or an attached source's key and root-layer identifier.
- A binding's stages are made on first use, and compared with the bindings that exist whenever those may have
  changed (prune).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .binding_stages import AttachedBindingStages, FileBindingStages
from .sources import AttachedSource, FileSource

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..binding_ids import BindingId


class StageRegistry:
    """The stages of the process's bindings, by binding identifier."""

    _stages: dict[BindingId, FileBindingStages | AttachedBindingStages]

    def __init__(self) -> None:
        self._stages = {}

    def file(self, binding_id: BindingId, root: str | os.PathLike[str]) -> FileBindingStages:
        """The binding's stages on the file root, made if it has none; its source stage opens at the first acquisition.

        Stages on another root are replaced, as when a "//" path resolves elsewhere after the .blend is
        saved elsewhere: the new file opens, and the old stage is let go.
        """
        found = self._stages.get(binding_id)
        if isinstance(found, FileBindingStages) and found.source.root == os.fspath(root):
            return found
        stages = self._stages[binding_id] = FileBindingStages(FileSource(root))
        return stages

    def attached(self, binding_id: BindingId, key: str) -> AttachedBindingStages:
        """The binding's stages on an attached source, made unattached if it has none.

        Existing ones keep their attachment.
        """
        found = self._stages.get(binding_id)
        if isinstance(found, AttachedBindingStages):
            return found
        stages = self._stages[binding_id] = AttachedBindingStages(AttachedSource(key))
        return stages

    def get(self, binding_id: BindingId) -> FileBindingStages | AttachedBindingStages | None:
        """The binding's stages, or None before their first use."""
        return self._stages.get(binding_id)

    def __contains__(self, binding_id: BindingId) -> bool:
        return binding_id in self._stages

    def __len__(self) -> int:
        return len(self._stages)

    def release(self, key: str) -> None:
        """Release the stage attached under key from every binding with that key, which leaves them unattached.

        Including bindings that are gone, whose attachment prune leaves.
        """
        for stages in self._stages.values():
            if isinstance(stages, AttachedBindingStages) and stages.source.key == key:
                stages.release()

    def prune(self, synchronizable: Mapping[BindingId, bool]) -> None:
        """Drop the stages of bindings that are gone, and of file bindings that can't synchronize.

        synchronizable maps every binding that exists to whether it can synchronize: one can't when its
        configuration can't be read, or it has copies and no canonical candidate. An attached binding that
        is gone loses only its evaluation stage; its attachment stays until release(key).
        """
        for binding_id, stages in list(self._stages.items()):
            if isinstance(stages, FileBindingStages):
                if not synchronizable.get(binding_id, False):
                    del self._stages[binding_id]  # reopening its file costs one open
            elif binding_id not in synchronizable:
                # Undo neither restores nor removes attachments (UNDO-06), so redo brings the binding back
                # attached; release(key) still releases it.
                stages.drop_evaluation_stage()
