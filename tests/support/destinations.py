"""A binding's destination, found through its records (lifecycle.md#binding-state)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from proscenium.binding.runtime import binding_configs

if TYPE_CHECKING:
    import bpy

    from proscenium.api.bindings import BindingHandle


def destination(handle: BindingHandle) -> bpy.types.Collection:
    """The collection holding the binding's canonical record: its configuration, last attempt, and generation."""
    found = binding_configs.find_binding(handle.binding_id)
    assert found is not None and found.destination is not None
    return found.destination
