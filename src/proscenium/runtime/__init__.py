"""Disposable in-memory state built from the records (lifecycle.md#undo-and-runtime-state).

The middle tier: it may import proscenium.persistence and proscenium.core, never proscenium.api. Callers
use what this module exports. The state itself is proscenium.runtime.state's, lookups by binding
identity are proscenium.runtime.binding_configs', and ownership is proscenium.runtime.ownership_index's.
"""

from .binding_configs import (
    Disabled,
    attached_with_key,
    binding_ids,
    binding_scene,
    config,
    configs,
    copied_bindings,
    create,
    set_config,
)
from .ownership_index import Claim, claims_on, manifest, resource, set_manifest, unreadable_manifests, update_manifest
from .state import NotTracking, find_copies, invalidate, rebuilds, start, stop

__all__ = [
    "Claim",
    "Disabled",
    "NotTracking",
    "attached_with_key",
    "binding_ids",
    "binding_scene",
    "claims_on",
    "config",
    "configs",
    "copied_bindings",
    "create",
    "find_copies",
    "invalidate",
    "manifest",
    "rebuilds",
    "resource",
    "set_config",
    "set_manifest",
    "start",
    "stop",
    "unreadable_manifests",
    "update_manifest",
]
