"""Every binding's source, by binding identifier.

Source stages, evaluation stages, and attachments are runtime state keyed by binding identity: they live in this
module, not in Blender data, so they are never saved in the .blend and undo neither restores nor
removes them. A file source's path, and an attached source's key and root-layer identifier, are
binding configuration, which the binding's records keep (proscenium.bindings); attaching under a
source key reads them there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .binding_source import BindingSource
from .sources import AttachedSource, FileSource

if TYPE_CHECKING:
    import os

    from pxr import Usd


class SourceRegistry:
    """The sources of the process's bindings, by binding identifier."""

    _bindings: dict[str, BindingSource]

    def __init__(self) -> None:
        self._bindings = {}

    def add_file(
        self, binding_id: str, root: str | os.PathLike[str], payload_policy: Usd.Stage.InitialLoadSet
    ) -> BindingSource:
        """Register a binding with a file source; its source stage opens at the first acquisition."""
        return self._add(binding_id, BindingSource(FileSource(root), payload_policy))

    def add_attached(self, binding_id: str, key: str, payload_policy: Usd.Stage.InitialLoadSet) -> BindingSource:
        """Register a binding with an attached source, unattached."""
        return self._add(binding_id, BindingSource(AttachedSource(key), payload_policy))

    def items(self) -> list[tuple[str, BindingSource]]:
        """Every binding's identifier and source, as a list, so sources can be removed while going through it."""
        return list(self._bindings.items())

    def __contains__(self, binding_id: str) -> bool:
        return binding_id in self._bindings

    def get(self, binding_id: str) -> BindingSource:
        """The source of binding_id. Raises KeyError if there is none."""
        return self._bindings[binding_id]

    def remove(self, binding_id: str) -> None:
        del self._bindings[binding_id]

    def _add(self, binding_id: str, binding: BindingSource) -> BindingSource:
        """Raises ValueError if binding_id is registered."""
        if binding_id in self._bindings:
            raise ValueError(f"Binding {binding_id!r} is already registered")
        self._bindings[binding_id] = binding
        return binding
