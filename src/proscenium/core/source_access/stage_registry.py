"""Every binding's stages, by binding identifier, and when each is made, kept, and let go.

Source stages, evaluation stages, and attachments are runtime state keyed by binding identity: they live in this
module, not in Blender data, so they are never saved in the .blend and undo neither restores nor
removes them (UNDO-06). A file source's path, and an attached source's key and root-layer identifier, are
binding configuration, which the binding's records keep (proscenium.persistence.binding_records); attaching under a
source key reads them there. A binding's stages are made from its configuration on first use, and compared
with the bindings that exist whenever they may have changed (prune).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .binding_stages import AttachedBindingStages, FileBindingStages
from .sources import AttachedSource, FileSource

if TYPE_CHECKING:
    from collections.abc import Collection


class StageRegistry:
    """The stages of the process's bindings, by binding identifier."""

    _stages: dict[str, FileBindingStages | AttachedBindingStages]

    def __init__(self) -> None:
        self._stages = {}

    def file(self, binding_id: str, root: str | os.PathLike[str]) -> FileBindingStages:
        """The binding's stages on the file root, made if it has none; its source stage opens at the first acquisition.

        Stages on another root are replaced, as when a "//" path resolves elsewhere after the .blend is
        saved elsewhere: the new file opens, and the old stage is let go.
        """
        found = self._stages.get(binding_id)
        if isinstance(found, FileBindingStages) and found.source.root == os.fspath(root):
            return found
        stages = self._stages[binding_id] = FileBindingStages(FileSource(root))
        return stages

    def attached(self, binding_id: str, key: str) -> AttachedBindingStages:
        """The binding's stages on an attached source, made unattached if it has none.

        Existing ones keep their attachment.
        """
        found = self._stages.get(binding_id)
        if isinstance(found, AttachedBindingStages):
            return found
        stages = self._stages[binding_id] = AttachedBindingStages(AttachedSource(key))
        return stages

    def get(self, binding_id: str) -> FileBindingStages | AttachedBindingStages | None:
        """The binding's stages, or None before their first use."""
        return self._stages.get(binding_id)

    def __contains__(self, binding_id: str) -> bool:
        return binding_id in self._stages

    def __len__(self) -> int:
        return len(self._stages)

    def release(self, key: str) -> None:
        """Release the stage attached under key from every binding with that key, which leaves them unattached.

        Whether or not their binding still exists: one that doesn't keeps its attachment (prune).
        """
        for stages in self._stages.values():
            if isinstance(stages, AttachedBindingStages) and stages.source.key == key:
                stages.release()

    def prune(self, existing: Collection[str], inactive: Collection[str]) -> None:
        """Let go of the stages of bindings that no longer exist, or can't synchronize.

        existing holds the identifiers of the bindings that exist, and inactive those of them that can't
        synchronize: their configuration can't be read, or they have copies and no canonical candidate. A
        file source's stage is dropped with its binding's stages; reopening it costs one open. An attached
        source keeps its attachment, since undo neither restores nor removes attachments (UNDO-06), so a
        binding redo brings back is still attached, and drops only its evaluation stage; release(key)
        still releases it. An inactive binding keeps its attachment and evaluation stage, as a binding
        that exists does.
        """
        for binding_id, stages in list(self._stages.items()):
            if isinstance(stages, FileBindingStages):
                if binding_id not in existing or binding_id in inactive:
                    del self._stages[binding_id]
            elif binding_id not in existing:
                stages.drop_evaluation_stage()
