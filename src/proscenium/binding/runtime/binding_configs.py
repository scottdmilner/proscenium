"""Lookups by binding identity, binding creation, and configuration writes, on the records as they are.

A lookup reads the identity's binding records and the binding index when it's called, reaches the binding record of
its canonical candidate, its canonical record, and returns what it finds as a FoundBinding: usable, with its
configuration; unreadable, with why (lifecycle.md#schema-versions); or disabled, with its copies
(source-access.md#copied-bindings). A write to a binding that isn't usable raises. A binding whose destination or
target scene is removed is no longer found (lifecycle.md#removed-destination). Nothing is held between calls, so a
load, undo, redo, or removal needs nothing done (DECISIONS.md "Binding records read when called").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..persistence import configs, records
from ..source_access import canonical_candidate
from . import copy_detection

if TYPE_CHECKING:
    import bpy

    from ..source_access import binding_settings, identifiers
    from .copy_detection import BindingRecord, CopiedBinding, IdentityCandidates


@dataclass(frozen=True, slots=True)
class FoundBinding:
    """A binding as a lookup by identity finds it. Exactly one of config, unreadable, and copies is set."""

    binding_id: identifiers.BindingId
    destination: bpy.types.Collection | None  # the collection holding its canonical record; None if it is disabled
    scene: bpy.types.Scene | None  # its target scene, if its configuration can be read and it isn't disabled
    config: configs.BindingConfig | None  # its configuration, if it is usable
    unreadable: records.RefusedRecord | None  # why its configuration can't be read, if it can't
    copies: CopiedBinding | None  # its candidates, and why none is canonical, if it is disabled

    @property
    def usable(self) -> bool:
        """Whether the binding can be used: its configuration can be read, and it isn't disabled."""
        return self.config is not None

    def usable_config(self) -> configs.BindingConfig:
        """The configuration; raises RefusedRecordError or DisabledBindingError for a binding that isn't usable."""
        if self.unreadable is not None:
            raise records.RefusedRecordError(self.unreadable)
        if self.copies is not None:
            raise DisabledBindingError(self.copies)
        assert self.config is not None
        return self.config


class DisabledBindingError(LookupError):  # raised like KeyError
    """A binding with copies and no canonical candidate was asked for its configuration, or written to."""

    copies: CopiedBinding

    def __init__(self, copies: CopiedBinding) -> None:
        super().__init__(f"binding {copies.binding_id} has copies and no canonical candidate ({copies.reason})")
        self.copies = copies


def find_binding(binding_id: identifiers.BindingId) -> FoundBinding | None:
    """The binding, or None if no binding has this identifier."""
    identity = copy_detection.candidates_for_binding(binding_id)
    return None if identity is None else _binding_from_candidates(binding_id, identity)


def find_bindings(scene: bpy.types.Scene | None = None) -> list[FoundBinding]:
    """The bindings, in the order found.

    With scene, those whose canonical candidate names it as their target scene, or, for a binding with none, those with
    a candidate naming it.
    """
    listed = []
    for binding_id, identity in copy_detection.candidates_by_binding().items():
        canonical = identity.canonical_record()
        reached = identity.candidates if canonical is None else (canonical,)
        if scene is None or any(_record_belongs_to_scene(r, scene) for r in reached):
            listed.append(_binding_from_candidates(binding_id, identity))
    return listed


def copied_bindings() -> list[CopiedBinding]:
    """Every binding identity that isn't unique, with its candidates and the rule's decision."""
    return [
        copy_detection.copied_binding_report(binding_id, identity)
        for binding_id, identity in copy_detection.candidates_by_binding().items()
        if identity.decision.reason is not canonical_candidate.CanonicalCandidateReason.UNIQUE
    ]


def create(scene: bpy.types.Scene, settings: binding_settings.RequestedSettings, name: str) -> identifiers.BindingId:
    """Make an unattached binding on scene requesting settings, and record it; it has no manifest yet.

    Returns its identifier. Raises what configs.create_binding raises.
    """
    return configs.create_binding(scene, settings, name).binding_id


def set_config(binding_id: identifiers.BindingId, config: configs.BindingConfig) -> None:
    """Store a binding's changed configuration; an unchanged one writes nothing.

    Raises RefusedRecordError, changing nothing, over one that can't be read; KeyError if there's no such binding;
    DisabledBindingError if it has no canonical candidate.
    """
    record = require_canonical_binding_record(binding_id)
    # write_config refuses only an unreadable or newer record, so an invalid one is refused here.
    if isinstance(record.config, records.RefusedRecord):
        raise records.RefusedRecordError(record.config)
    if config == record.config:
        return
    configs.write_config(record.collection, binding_id, config)
    restore_missing_binding_index_entry(binding_id, record)


def require_canonical_binding_record(binding_id: identifiers.BindingId) -> BindingRecord:
    """The binding's canonical record, readable or not.

    Raises KeyError if no binding has this identifier, and DisabledBindingError if it has no canonical candidate.
    """
    identity = copy_detection.candidates_for_binding(binding_id)
    if identity is None:
        raise KeyError(binding_id)
    if (record := identity.canonical_record()) is None:
        raise DisabledBindingError(copy_detection.copied_binding_report(binding_id, identity))
    return record


def restore_missing_binding_index_entry(binding_id: identifiers.BindingId, record: BindingRecord) -> None:
    """Write the binding index entry a unique binding is missing, after a write to its records.

    Only when the index has no entry for the identity, or one naming no collection, so it names the binding's
    destination (source-access.md#canonical-candidate). A file with two indexes, or one that can't be read, is left
    alone. Writes restore entries; detection never does.
    """
    if isinstance(record.config, records.RefusedRecord):
        return
    try:
        configs.restore_index_entry(binding_id, record.collection)
    except (ValueError, records.RefusedRecordError):
        return


def _record_belongs_to_scene(record: BindingRecord, scene: bpy.types.Scene) -> bool:
    """Whether the record is on scene: its target scene, or for one that can't be read, one linking its collection."""
    if isinstance(record.config, records.RefusedRecord):
        return record.collection in scene.collection.children_recursive
    return record.scene == scene


def _binding_from_candidates(binding_id: identifiers.BindingId, identity: IdentityCandidates) -> FoundBinding:
    """Build a binding lookup result from its candidates and canonical decision."""
    if (record := identity.canonical_record()) is None:
        return FoundBinding(
            binding_id, None, None, None, None, copy_detection.copied_binding_report(binding_id, identity)
        )
    if isinstance(record.config, records.RefusedRecord):
        return FoundBinding(binding_id, record.collection, None, None, record.config, None)
    return FoundBinding(binding_id, record.collection, record.scene, record.config, None, None)
