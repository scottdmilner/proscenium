"""Lookups by binding identity, binding creation, and configuration writes, through the bindings' state.

A lookup reaches the binding record of the identity's canonical candidate, its canonical record, after checking every
candidate the rule decides on, and returns what it finds as a FoundBinding: usable, with its configuration; unreadable,
with why (lifecycle.md#schema-versions); or disabled, with its copies (source-access.md#copied-bindings). A write to a
binding that isn't usable raises. A binding whose destination or target scene is removed is no longer found
(lifecycle.md#removed-destination).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..persistence import configs, records
from ..source_access import canonical_candidate
from . import copy_detection, state
from .state import StaleError

if TYPE_CHECKING:
    import bpy

    from ..source_access import binding_settings, identifiers
    from .copy_detection import CopiedBinding, IdentityCandidates
    from .state import BindingRecord, State


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
    return state.query(lambda s: _found_in(s, binding_id))


def find_bindings(scene: bpy.types.Scene | None = None) -> list[FoundBinding]:
    """The bindings, in the order they were found or made; one pass over the state.

    With scene, those whose canonical candidate names it as their target scene, or, for a binding with none, those with
    a candidate naming it. Every candidate is checked.
    """
    return state.query(lambda s: _listed(s, scene))


def copied_bindings() -> list[CopiedBinding]:
    """Every binding identity that isn't unique, with its candidates and the rule's decision."""
    return state.query(_copied)


def create(scene: bpy.types.Scene, settings: binding_settings.RequestedSettings, name: str) -> identifiers.BindingId:
    """Make an unattached binding on scene requesting settings, and record it; it has no manifest yet.

    Returns its identifier. Raises NotRegisteredError before changing anything, and what configs.create_binding
    raises.
    """
    current = state.current_state()
    created = configs.create_binding(scene, settings, name)
    current.add_binding(created)
    return created.binding_id


def set_config(binding_id: identifiers.BindingId, config: configs.BindingConfig) -> None:
    """Store a binding's changed configuration; an unchanged one writes nothing.

    Raises RefusedRecordError, changing nothing, over one that can't be read; KeyError if there's no such binding;
    DisabledBindingError if it has no canonical candidate.
    """
    record = required_record(binding_id)
    # write_config refuses only an unreadable or newer record, so an invalid one is refused here.
    if isinstance(record.config, records.RefusedRecord):
        raise records.RefusedRecordError(record.config)
    if config == record.config:
        return
    configs.write_config(record.collection, binding_id, config)
    record.held.configs[binding_id] = config
    restore_entry(binding_id, record)


def required_record(binding_id: identifiers.BindingId) -> BindingRecord:
    """The binding's canonical record, readable or not.

    Raises KeyError if no binding has this identifier, and DisabledBindingError if it has no canonical candidate.
    """
    return state.query(lambda s: required_record_in(s, binding_id))


def required_record_in(current: State, binding_id: identifiers.BindingId) -> BindingRecord:
    """required_record(), as a question for state.query: the binding's canonical record in current."""
    identity = current.identities.get(binding_id)
    if identity is None:
        raise KeyError(binding_id)
    _check_candidates(binding_id, identity)
    if (record := identity.canonical_record()) is None:
        raise DisabledBindingError(copy_detection.report(binding_id, identity))
    return record


def restore_entry(binding_id: identifiers.BindingId, record: BindingRecord) -> None:
    """Write the binding index entry a unique binding is missing, after a write to its records.

    Only when the index has no entry for the identity, or one naming no collection, so it names the binding's
    destination (source-access.md#canonical-candidate). A file with two indexes, or one that can't be read, is left
    alone. Writes restore entries; detection never does.
    """
    current = state.current_state()
    entries = current.identities[binding_id].index_entries
    if (entries and entries != (None,)) or isinstance(record.config, records.RefusedRecord):
        return
    try:
        written = configs.restore_index_entry(binding_id, record.collection)
    except (ValueError, records.RefusedRecordError):
        return
    if written is not None:
        current.replace_index(binding_id, written)


def _found_in(current: State, binding_id: identifiers.BindingId) -> FoundBinding | None:
    identity = current.identities.get(binding_id)
    return None if identity is None else _found(binding_id, identity)


def _listed(current: State, scene: bpy.types.Scene | None) -> list[FoundBinding]:
    listed = []
    for binding_id, identity in current.identities.items():
        if scene is not None and not any(_on(r, scene) for r in identity.candidates):
            continue  # none on scene, so it can't be listed there, whatever the rule decides: not checked
        found = _found(binding_id, identity)
        canonical = identity.canonical_record()
        reached = identity.candidates if canonical is None else (canonical,)
        if scene is None or any(_on(r, scene) for r in reached):
            listed.append(found)
    return listed


def _on(record: BindingRecord, scene: bpy.types.Scene) -> bool:
    """Whether the record is on scene: its target scene, or for one that can't be read, one linking its collection."""
    if isinstance(record.config, records.RefusedRecord):
        return record.collection in scene.collection.children_recursive
    return record.scene == scene


def _copied(current: State) -> list[CopiedBinding]:
    copied = []
    for binding_id, identity in current.identities.items():
        if identity.decision.reason is not canonical_candidate.DecisionReason.UNIQUE:
            _check_candidates(binding_id, identity)
            copied.append(copy_detection.report(binding_id, identity))
    return copied


def _found(binding_id: identifiers.BindingId, identity: IdentityCandidates) -> FoundBinding:
    """The binding an identity is, checked."""
    _check_candidates(binding_id, identity)
    if (record := identity.canonical_record()) is None:
        return FoundBinding(binding_id, None, None, None, None, copy_detection.report(binding_id, identity))
    if isinstance(record.config, records.RefusedRecord):
        return FoundBinding(binding_id, record.collection, None, None, record.config, None)
    return FoundBinding(binding_id, record.collection, record.scene, record.config, None, None)


def _check_candidates(binding_id: identifiers.BindingId, identity: IdentityCandidates) -> None:
    """Raise StaleError if any candidate of the identity is gone: the rule's decision may have been different."""
    if not all(state.valid(binding_id, record) for record in identity.candidates):
        raise StaleError
