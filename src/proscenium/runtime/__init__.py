"""Disposable in-memory state built from the records (lifecycle.md#undo-and-runtime-state).

The middle tier: it may import proscenium.persistence and proscenium.core, never proscenium.api. Callers
use what this module exports. The state itself is proscenium.runtime.state's, lookups by binding
identity are proscenium.runtime.binding_configs', and ownership is proscenium.runtime.ownership_index's.
"""

from .binding_configs import (
    BindingDisabledError,
    attached_with_key,
    binding_ids,
    binding_scene,
    config,
    configs,
    copied_bindings,
    create,
    set_config,
)
from .ownership_index import (
    Claim,
    claims_on,
    manifest,
    resource,
    set_manifest,
    set_manifest_entries,
    unreadable_manifests,
)
from .state import NotRegisteredError, invalidate, rebuild_count, refresh_if_tags_changed, start, stop

__all__ = [
    "Claim",
    "BindingDisabledError",
    "NotRegisteredError",
    "attached_with_key",
    "binding_ids",
    "binding_scene",
    "claims_on",
    "config",
    "configs",
    "copied_bindings",
    "create",
    "refresh_if_tags_changed",
    "invalidate",
    "manifest",
    "rebuild_count",
    "resource",
    "set_config",
    "set_manifest",
    "start",
    "stop",
    "unreadable_manifests",
    "set_manifest_entries",
]
