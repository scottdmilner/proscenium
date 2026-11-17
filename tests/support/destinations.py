"""A binding's destination, found through its records (lifecycle.md#binding-state)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from proscenium_sync.runtime import binding_operations

if TYPE_CHECKING:
    import bpy

    from proscenium_sync.bindings import BindingHandle


def destination(handle: BindingHandle) -> bpy.types.Collection:
    """The collection holding the binding's canonical record: its configuration, last attempt, and generation."""
    found = binding_operations.find_binding(handle.binding_id)
    assert found is not None and found.destination is not None
    return found.destination
