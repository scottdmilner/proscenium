"""Disposable in-memory state built from the records (lifecycle.md#undo-and-runtime-state).

The upper tier of proscenium.binding: it may import proscenium.binding.persistence and the bpy-free code, never
proscenium.api. Callers use what this module exports: what proscenium.api, proscenium.synchronization, and
proscenium.addon call, and the errors that reach their callers. The state itself is proscenium.binding.runtime.state's,
lookups by binding identity are proscenium.binding.runtime.binding_configs', ownership is
proscenium.binding.runtime.ownership_index's, and the pending-cleanup ledger
proscenium.binding.runtime.pending_cleanup's.
"""

from .binding_configs import (
    DisabledBindingError,
    FoundBinding,
    copied_bindings,
    create,
    find_binding,
    find_bindings,
    set_config,
)
from .copy_detection import CopiedBinding
from .current_stages import CurrentStages
from .ownership_index import manifest
from .pending_cleanup import ledger, set_ledger_entries
from .state import NotRegisteredError, invalidate, refresh_if_tags_changed, start_tracking, stop_tracking

__all__ = [
    "CopiedBinding",
    "CurrentStages",
    "DisabledBindingError",
    "FoundBinding",
    "NotRegisteredError",
    "copied_bindings",
    "create",
    "find_binding",
    "find_bindings",
    "invalidate",
    "ledger",
    "manifest",
    "refresh_if_tags_changed",
    "set_config",
    "set_ledger_entries",
    "start_tracking",
    "stop_tracking",
]
