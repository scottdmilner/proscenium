"""Every binding's source, by binding identifier, and attachment under source keys.

Source stages, evaluation stages, and attachments are runtime state keyed by binding identity: they live in this
module, not in Blender data, so they are never saved in the .blend and undo neither restores nor
removes them. A file source's path, and an attached source's key and root-layer identifier, are
binding configuration, which is saved in the .blend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .binding_source import BindingSource
from .sources import AttachedSource, FileSource

if TYPE_CHECKING:
    import os

    from pxr import Usd


@dataclass(frozen=True)
class AttachResult:
    """What attaching a stage under a source key did."""

    attached: tuple[str, ...]  # binding identifiers now evaluating the stage; empty if refused or none has the key
    unconfirmed: tuple[str, ...]  # bindings whose stored root-layer identifier differs; non-empty: nothing attached


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

    def add_attached(
        self,
        binding_id: str,
        key: str,
        payload_policy: Usd.Stage.InitialLoadSet,
        root_layer_identifier: str | None = None,
    ) -> BindingSource:
        """Register a binding with an attached source, unattached."""
        return self._add(binding_id, BindingSource(AttachedSource(key, root_layer_identifier), payload_policy))

    def get(self, binding_id: str) -> BindingSource:
        """The source of binding_id. Raises KeyError if there is none."""
        return self._bindings[binding_id]

    def remove(self, binding_id: str) -> None:
        del self._bindings[binding_id]

    def attach(self, key: str, stage: Usd.Stage, *, confirm: bool = False) -> AttachResult:
        """Attach stage to every binding whose attached source has this exact source key.

        If any of those bindings stored a root-layer identifier other than stage's, the caller
        must pass confirm=True. Otherwise no binding is changed, and the result lists the
        bindings whose identifier differs.
        """
        identifier = stage.GetRootLayer().identifier
        matching = {
            binding_id: binding.source
            for binding_id, binding in self._bindings.items()
            if isinstance(binding.source, AttachedSource) and binding.source.key == key
        }
        unconfirmed = tuple(
            binding_id
            for binding_id, source in matching.items()
            if source.root_layer_identifier not in (None, identifier)
        )
        if unconfirmed and not confirm:
            return AttachResult(attached=(), unconfirmed=unconfirmed)
        for source in matching.values():
            source.attach(stage)
        return AttachResult(attached=tuple(matching), unconfirmed=())

    def _add(self, binding_id: str, binding: BindingSource) -> BindingSource:
        """Raises ValueError if binding_id is registered."""
        if binding_id in self._bindings:
            raise ValueError(f"Binding {binding_id!r} is already registered")
        self._bindings[binding_id] = binding
        return binding
