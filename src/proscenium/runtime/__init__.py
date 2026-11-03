"""Disposable in-memory state built from the records (lifecycle.md#undo-and-runtime-state).

The middle tier: it may import proscenium.persistence and the bpy-free code below the tiers, never
proscenium.api. Callers use what this module exports: what proscenium.api and proscenium.addon call, and the
errors that reach their callers. The state itself is proscenium.runtime.state's, lookups by binding identity are
proscenium.runtime.binding_configs', and ownership is proscenium.runtime.ownership_index's.
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
from .state import NotRegisteredError, invalidate, refresh_if_tags_changed, start, stop

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
    "refresh_if_tags_changed",
    "set_config",
    "start",
    "stop",
]
