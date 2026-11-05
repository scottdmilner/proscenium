"""Disposable in-memory state built from the records (lifecycle.md#undo-and-runtime-state).

The upper tier of proscenium.binding: it may import proscenium.binding.persistence and the bpy-free code. It exports
its modules: the state itself (state), lookups by binding identity (binding_configs), copied-binding detection
(copy_detection), every binding's stages (stage_tracking), ownership (ownership_index), and the pending-cleanup ledger
(pending_cleanup).
"""

from . import binding_configs, copy_detection, ownership_index, pending_cleanup, stage_tracking, state

__all__ = ["binding_configs", "copy_detection", "ownership_index", "pending_cleanup", "stage_tracking", "state"]
