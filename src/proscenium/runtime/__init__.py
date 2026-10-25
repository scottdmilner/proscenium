"""Disposable in-memory state built from the records (lifecycle.md#undo-and-runtime-state).

The middle tier: it may import proscenium.persistence and proscenium.core, never proscenium.api. Callers
use what this module exports. The state itself is proscenium.runtime.state's, lookups by binding
identity are proscenium.runtime.binding_configs', and ownership is proscenium.runtime.ownership_index's.
"""

from .binding_configs import (
    BindingStatus,
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
from .ownership_index import (
    Claim,
    Ownership,
    OwnershipStatus,
    manifest,
    ownership,
    set_manifest,
    set_manifest_entries,
)
from .state import NotRegisteredError, invalidate, rebuild_count, refresh_if_tags_changed, start, stop

__all__ = [
    "BindingStatus",
    "Claim",
    "CopiedBinding",
    "CurrentStages",
    "DisabledBindingError",
    "FoundBinding",
    "NotRegisteredError",
    "Ownership",
    "OwnershipStatus",
    "copied_bindings",
    "create",
    "find_binding",
    "find_bindings",
    "invalidate",
    "manifest",
    "ownership",
    "rebuild_count",
    "refresh_if_tags_changed",
    "set_config",
    "set_manifest",
    "set_manifest_entries",
    "start",
    "stop",
]
